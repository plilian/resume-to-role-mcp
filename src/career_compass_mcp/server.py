from __future__ import annotations

import json
import hashlib
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp.server import MCPServer

from .documents import numbers, render_docs, split_resume
from .matching import ats_estimate, eligibility, rank_evidence, score_job, terms
from .preferences import (LANGUAGE_NAMES, detect_language, effective_preferences, infer_mobility_support,
                          infer_work_arrangement, normalize_language, normalize_mobility_support,
                          normalize_work_arrangements)
from .sources import base, crawl_career_sites, make_search_queries, search_company_boards, search_public_feeds
from .store import Store, data_dir

mcp=MCPServer("career-compass")
store=Store()

def _infer_work_mode(item: dict[str,Any]) -> None:
    item["remote"]=infer_work_arrangement(item)
    support=infer_mobility_support(item)
    status=str(item.get("eligibility","unknown")).lower()
    if status=="relocation available" and "relocation" not in support: support.append("relocation")
    if status=="sponsorship available" and "visa_sponsorship" not in support: support.append("visa_sponsorship")
    item["mobility_support"]=support

@mcp.tool()
def profile_get() -> dict[str,Any]:
    """Return the local profile, supported interaction/document languages, and optional work-mode/mobility filters."""
    profile=store.profile()
    profile.setdefault("preferred_language","en")
    profile.setdefault("document_language","job")
    profile.setdefault("search_languages",[])
    arrangements,mobility=effective_preferences(profile)
    profile["work_arrangements"]=arrangements
    profile["mobility_support"]=mobility
    return {"profile":profile,"resumes":[{"id":x["id"],"name":x["name"],"chars":x["chars"]} for x in store.resumes()],
      "supported_options":{"languages":[{"code":code,"name":name,"direction":"rtl" if code in {"fa","ar"} else "ltr"} for code,name in LANGUAGE_NAMES.items()],
        "document_language":["job",*LANGUAGE_NAMES.keys()],
        "work_arrangements":["remote","hybrid","in_person","other"],
        "mobility_support":["relocation","visa_sponsorship"],
        "empty_work_filters":"No arrangement or mobility filtering; search all work types."}}

@mcp.tool()
def profile_update(profile_json: str) -> dict[str,Any]:
    """Update profile JSON fields. preferred_language controls assistant replies; document_language is job or en/fa/es/ar. search_languages, work_arrangements, and mobility_support are optional arrays. Empty work filters mean search all arrangements."""
    try: data=json.loads(profile_json)
    except json.JSONDecodeError as e: raise ValueError(f"Invalid JSON: {e}")
    if not isinstance(data,dict): raise ValueError("profile_json must be a JSON object")
    list_fields=("target_titles","countries","remote_preferences","work_arrangements","mobility_support","search_languages","seniority","languages","resume_roots")
    for key in list_fields:
        if key in data and (not isinstance(data[key],list) or any(not isinstance(v,str) for v in data[key])):
            raise ValueError(f"{key} must be a list of strings")
    if "preferred_language" in data: data["preferred_language"]=normalize_language(data["preferred_language"])
    if "document_language" in data: data["document_language"]=normalize_language(data["document_language"],allow_job=True)
    if "search_languages" in data:
        data["search_languages"]=list(dict.fromkeys(normalize_language(value) for value in data["search_languages"]))
    if "work_arrangements" in data: data["work_arrangements"]=normalize_work_arrangements(data["work_arrangements"])
    if "mobility_support" in data: data["mobility_support"]=normalize_mobility_support(data["mobility_support"])
    return store.update_profile(data)

@mcp.tool()
def resume_list() -> dict[str,Any]:
    """List imported resumes, without returning their private filesystem paths."""
    return {"resumes":[{"id":x["id"],"name":x["name"],"chars":x["chars"],"imported_at":x["imported_at"]} for x in store.resumes()]}

@mcp.tool()
def resume_import(paths: list[str]) -> dict[str,Any]:
    """Import PDF, DOCX, TXT, or Markdown resume files from explicitly configured profile.resume_roots only. A configured folder is scanned recursively for supported files."""
    profile=store.profile(); roots=[Path(x).expanduser().resolve() for x in profile.get("resume_roots",[])]
    if not roots: raise ValueError("Set resume_roots in profile_update to the candidate's chosen resume folder(s) first.")
    allowed={".pdf",".docx",".txt",".md"}; candidates=[]
    for raw in paths[:30]:
        p=Path(raw).expanduser().resolve(strict=True)
        if not any(p==root or root in p.parents for root in roots): raise ValueError(f"Path is outside configured resume_roots: {p}")
        if p.is_file(): candidates.append(p)
        elif p.is_dir():
            for root,dirs,files in __import__("os").walk(p,followlinks=False):
                dirs[:]=[d for d in dirs if not (Path(root)/d).is_symlink()]
                for filename in files:
                    q=Path(root)/filename
                    if q.suffix.lower() in allowed: candidates.append(q)
                    if len(candidates)>=500: break
                if len(candidates)>=500: break
    seen=set(); imported=[]; failures=[]
    for p in candidates:
        try:
            if p in seen or p.suffix.lower() not in allowed: continue
            seen.add(p); text,chunks=split_resume(str(p)); rid=__import__("hashlib").sha1(str(p).encode()).hexdigest()[:12]
            store.save_resume(rid,str(p),p.name,text,chunks); imported.append({"id":rid,"name":p.name,"evidence_chunks":len(chunks)})
        except Exception as e: failures.append({"file":p.name,"error":str(e)[:240]})
    return {"imported":imported,"failures":failures,"total_resumes":len(store.resumes()),"note":"All imported resume text is stored locally with source filenames."}

@mcp.tool()
async def evidence_scan_websites(urls: list[str]|None=None) -> dict[str,Any]:
    """Scan candidate-owned or candidate-supplied portfolio, GitHub, and career pages for evidence; extracted pages stay unverified and matching-only until explicitly approved."""
    p=store.profile(); selected=urls or p.get("evidence_sources") or [p.get(k) for k in ("website_url","github_url","linkedin_url") if p.get(k)]
    if not selected: raise ValueError("Provide public candidate-owned career-source URLs or configure evidence_sources in profile_update.")
    pages,errors=await crawl_career_sites(selected); result=[]
    for page in pages:
        eid=__import__("hashlib").sha1(page["url"].encode()).hexdigest()[:14]
        store.save_web_evidence(eid,page["url"],page["title"],page["text"])
        result.append({"evidence_id":eid,"url":page["url"],"title":page["title"],"verification":"unverified","visibility":"matching_only","excerpt":page["text"][:900]})
    return {"pages_scanned":len(result),"evidence":result,"errors":errors,
      "next":"Review extracted career facts. Approve only accurate claims with evidence_set_visibility; web text is not a verified resume fact by itself."}

@mcp.tool()
def career_profile_overview(page: int=1, page_size: int=25) -> dict[str,Any]:
    """Build a provenance-preserving overview across all resumes: detected skill terms with source filenames plus a paginated page of evidence snippets."""
    evidence=[x for x in store.evidence() if x["visibility"] not in {"private","ignore"}]; skill_sources={}
    for item in evidence:
        for skill in terms(item["text"]):
            skill_sources.setdefault(skill,set()).add(item["source_name"])
    skills=[{"skill":k,"sources":sorted(v)} for k,v in sorted(skill_sources.items())]
    page=max(1,page); size=max(1,min(50,page_size)); start=(page-1)*size
    chunks=[{"id":x["id"],"source_name":x["source_name"],"verification":x["verification"],"visibility":x["visibility"],"text":x["text"][:1200]} for x in evidence]
    return {"resume_sources":[x["name"] for x in store.resumes()],"detected_skills":skills,
      "evidence":chunks[start:start+size],"page":page,"page_size":size,"total_evidence_chunks":len(chunks),
      "total_pages":(len(chunks)+size-1)//size,"note":"Skill detection is dictionary-based and may miss relevant phrases; use all source snippets and the host model for semantic analysis."}

@mcp.tool()
def evidence_set_visibility(evidence_ids: list[str], visibility: str, approved: bool=True) -> dict[str,Any]:
    """Approve or revoke scanned website evidence and control employer visibility: resume_cover_letter, resume_only, cover_letter_only, matching_only, private, or ignore."""
    allowed={"resume_cover_letter","resume_only","cover_letter_only","matching_only","private","ignore"}
    if visibility not in allowed: raise ValueError(f"visibility must be one of {sorted(allowed)}")
    if len(evidence_ids)>100: raise ValueError("Use at most 100 evidence IDs")
    evidence_ids=list(dict.fromkeys(evidence_ids))
    updated=store.web_evidence_visibility(evidence_ids,"approved" if approved else "unverified",visibility)
    if updated!=len(evidence_ids): raise ValueError("Some evidence IDs were not found in the website evidence store")
    return {"updated":updated,"verification":"approved" if approved else "unverified","visibility":visibility}

@mcp.tool()
def source_search_queries(page: int=1, page_size: int=10, localized_titles: list[str]|None=None) -> dict[str,Any]:
    """Generate paginated Google/Bing queries across job boards. Supply host-translated role titles for the candidate's selected search_languages; saved arrangement and mobility preferences are included."""
    p=store.profile(); arrangements,mobility=effective_preferences(p)
    qs=make_search_queries(p.get("target_titles",[]),p.get("countries",[]),arrangements,mobility,localized_titles)
    page=max(1,page); size=max(1,min(12,page_size)); start=(page-1)*size
    return {"queries":[{"source":q.split("site:")[-1],"query":q} for q in qs[start:start+size]],"page":page,"page_size":size,"total_queries":len(qs),"total_sources":26,"total_pages":(len(qs)+size-1)//size,
      "search_languages":p.get("search_languages",[])}

@mcp.tool()
async def discover_jobs(queries: list[str]|None=None, countries: list[str]|None=None, limit_per_source: int=80) -> dict[str,Any]:
    """Search Remote OK, Remotive, Arbeitnow, Jobicy, Himalayas, We Work Remotely RSS, and Bing job/career results. Uses target titles/countries from profile by default and stores normalized matches."""
    p=store.profile()
    if queries:
        q=queries[:8]
    else:
        target_titles=p.get("target_titles") or ["product manager","data analyst"]
        q=[" OR ".join(target_titles[i:i+4]) for i in range(0,min(len(target_titles),32),4)]
    c=(countries or p.get("countries") or [])[:12]
    arrangements,mobility=effective_preferences(p)
    ttl={"Remote OK":3600,"Remotive":21600,"Arbeitnow":3600,"Jobicy":3600,
         "Himalayas":86400,"We Work Remotely":3600,"Bing Search":3600}
    search_fingerprint=hashlib.sha256(json.dumps({"queries":q,"countries":c,"work_arrangements":arrangements,"mobility_support":mobility,"limit":limit_per_source},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    due=[name for name,seconds in ttl.items() if store.source_is_due(name,seconds,fingerprint=search_fingerprint)]
    if arrangements and "remote" not in arrangements:
        # Remote-only feeds cannot satisfy an onsite/flexible-only request; keep Bing
        # search active so general career pages and company postings are still found.
        due=[name for name in due if name=="Bing Search"]
    cached=[item for name in ttl if name not in due for item in store.jobs_by_source(name)]
    if due:
        fresh,errors=await search_public_feeds(q,c,limit_per_source,True,due,arrangements,mobility)
        for name in due: store.mark_source_attempt(name,name not in errors,search_fingerprint)
        listings=cached+fresh
    else:
        errors={}; listings=cached
    texts=store.all_candidate_text(); titles=p.get("target_titles",[]); saved=[]; skipped=0
    for item in listings:
        if not item.get("title") or not item.get("source_url"): skipped+=1; continue
        _infer_work_mode(item)
        item["eligibility"]=eligibility(item,c); item["match"]=score_job(item,texts,titles); jid=store.upsert_job(item); saved.append(jid)
    unique=list(dict.fromkeys(saved))
    return {"jobs_stored":len(unique),"duplicates_or_updates":len(saved)-len(unique),"invalid_listings_skipped":skipped,
      "source_errors":errors,"sources_attempted":due,"sources_served_from_local_cache":[name for name in ttl if name not in due],
      "source_refresh_windows_hours":{"Remote OK":1,"Remotive":6,"Arbeitnow":1,"Jobicy":1,"Himalayas":24,"We Work Remotely":1,"Bing Search":1},
      "note":"Some feeds are remote-only and some expose listing pages rather than direct apply forms. Check source and location eligibility on each result.","next":"Use job_list with page=1 to review ranked results."}

@mcp.tool()
async def company_board_search(board_type: str, board_ids: list[str], limit_per_board: int=100) -> dict[str,Any]:
    """Search public company career listings on Greenhouse, Lever, Ashby, or SmartRecruiters using board identifiers found by career-page search."""
    p=store.profile(); listings,errors=await search_company_boards(board_type,board_ids,limit_per_board); texts=store.all_candidate_text(); titles=p.get("target_titles",[]); countries=p.get("countries",[]); saved=[]
    for item in listings:
        if not item.get("title"): continue
        _infer_work_mode(item)
        item["eligibility"]=eligibility(item,countries); item["match"]=score_job(item,texts,titles); saved.append(store.upsert_job(item))
    return {"jobs_stored":len(set(saved)),"source":board_type,"boards_searched":board_ids[:40],"errors":errors}

@mcp.tool()
def ingest_web_jobs(results_json: str) -> dict[str,Any]:
    """Store job listings found by the host's signed-in Google/Bing search or browser. Provide JSON array with title, company, location, description, url, optional apply_url/source/posted_at/remote/eligibility. Preserve canonical page URLs; this tool does not submit applications."""
    try: results=json.loads(results_json)
    except json.JSONDecodeError as e: raise ValueError(f"Invalid JSON: {e}")
    if not isinstance(results,list): raise ValueError("Expected a JSON array")
    p=store.profile(); countries=p.get("countries",[]); titles=p.get("target_titles",[]); texts=store.all_candidate_text(); saved=[]; rejected=[]
    for i,x in enumerate(results[:100]):
        if not isinstance(x,dict): rejected.append({"index":i,"reason":"not an object"}); continue
        title=str(x.get("title","")).strip(); url=str(x.get("url","")).strip(); host=urlparse(url)
        if not title or host.scheme not in {"http","https"} or not host.netloc:
            rejected.append({"index":i,"reason":"title and valid public URL are required"}); continue
        item=base(str(x.get("source") or host.netloc),x.get("id") or url,title,x.get("company"),x.get("location"),x.get("description"),x.get("apply_url"),url,x.get("posted_at"),str(x.get("work_arrangement",x.get("remote","unknown"))),str(x.get("eligibility","unknown")))
        _infer_work_mode(item)
        item["eligibility"]=eligibility(item,countries); item["match"]=score_job(item,texts,titles); saved.append(store.upsert_job(item))
    return {"jobs_stored":len(set(saved)),"rejected":rejected,"note":"Search result pages remain labeled with their reported source; verify each original posting is live."}

@mcp.tool()
def job_list(page: int=1, page_size: int=25, status: str="", eligible_only: bool=True) -> dict[str,Any]:
    """List saved jobs by JD skill match then freshness. By default show only country/work-eligibility matches; paginate with page/page_size. Set eligible_only=false to inspect unknown or ineligible listings."""
    profile=store.profile(); arrangements,mobility=effective_preferences(profile)
    jobs,total=store.jobs(page,page_size,status,eligible_only,arrangements,mobility)
    size=max(1,min(100,page_size))
    return {"jobs":jobs,"eligibility_filter":"eligible and likely eligible only" if eligible_only else "all classifications",
      "work_arrangements_filter":arrangements,"mobility_support_filter":mobility,"page":max(1,page),"page_size":size,"total":total,"total_pages":(total+size-1)//size}

@mcp.tool()
def job_get(job_id: str) -> dict[str,Any]:
    """Get a full saved job description, match breakdown, source and original job/apply links."""
    job=store.job(job_id)
    if not job: raise ValueError("Unknown job id")
    return job

def _brief(job_id: str, evidence_limit: int=18, excerpt_limit: int=1400) -> dict[str,Any]:
    job=store.job(job_id)
    if not job: return {"job_id":job_id,"error":"Unknown job id"}
    query=job["title"]+"\n"+job["description"]; evidence=[x for x in store.evidence() if x["visibility"] not in {"private","ignore"}]; ranked=sorted(evidence,key=lambda e:rank_evidence(e["text"],query),reverse=True)
    ranked=[e for e in ranked if rank_evidence(e["text"],query)>0][:max(1,min(30,evidence_limit))]
    ranked=[{**e,"text":e["text"][:excerpt_limit]} for e in ranked]
    usable=[]; restricted=[]
    for item in ranked:
        if item["verification"]=="verified" or (item["verification"]=="approved" and item["visibility"] in {"resume_cover_letter","resume_only","cover_letter_only"}):
            usable.append(item)
        elif item["visibility"] not in {"private","ignore"}:
            restricted.append({"id":item["id"],"source_name":item["source_name"],"verification":item["verification"],"visibility":item["visibility"],"text":item["text"][:1000]})
    profile=store.profile(); profile.pop("resume_roots",None); profile.pop("evidence_sources",None)
    return {"job_id":job_id,"job":{"title":job["title"],"company":job["company"],"location":job["location"],"description":job["description"][:24000],"source":job["source"],"source_url":job["source_url"],"apply_url":job["apply_url"],"match":job["match"]},
      "candidate_profile":profile,"evidence":usable,"restricted_web_evidence":restricted,
      "evidence_note":"Resume snippets are candidate-supplied. Approved website snippets include their source URL. Restricted web evidence is for matching context only and must not appear in an employer-facing document."}

@mcp.tool()
def tailoring_brief(job_id: str, evidence_limit: int=18) -> dict[str,Any]:
    """Get a selected job's JD and provenance-labeled evidence snippets across all imported resumes for on-demand tailored document drafting."""
    return _brief(job_id,evidence_limit)

@mcp.tool()
def job_match_update(job_id: str, analysis_json: str) -> dict[str,Any]:
    """Save a semantic JD match made by the host model. Each claimed matched skill must cite evidence IDs and an exact supporting quote from those snippets. Overall score is matched JD skills divided by identified JD skills; role relevance is separate."""
    try: analysis=json.loads(analysis_json)
    except json.JSONDecodeError as e: raise ValueError(f"Invalid JSON: {e}")
    if not isinstance(analysis,dict): raise ValueError("analysis_json must be a JSON object")
    job=store.job(job_id)
    if not job: raise ValueError("Unknown job id")
    required=analysis.get("required_skills",[]); matched=analysis.get("matched_skills",[])
    if not isinstance(required,list) or any(not isinstance(x,str) for x in required): raise ValueError("required_skills must be an array of strings")
    required=list(dict.fromkeys(x.strip() for x in required if x.strip()))
    if not isinstance(matched,list) or any(not isinstance(x,dict) for x in matched): raise ValueError("matched_skills must be an array of evidence objects")
    if len(required)>100 or len(matched)>100: raise ValueError("Limit a match analysis to 100 skills")
    all_ids={x["id"]:x for x in store.evidence() if x["visibility"] not in {"private","ignore"}}; accepted=[]
    for entry in matched:
        skill=str(entry.get("skill","")).strip(); quote=str(entry.get("support_quote","")).strip(); ids=entry.get("evidence_ids",[])
        if not skill or not quote or not isinstance(ids,list) or not ids: raise ValueError("Each matched skill needs a name, exact support_quote, and evidence_ids")
        if any(eid not in all_ids for eid in ids): raise ValueError(f"Unknown evidence ID cited for {skill!r}")
        if not any(eid in all_ids and re.sub(r"\s+"," ",quote).lower() in re.sub(r"\s+"," ",all_ids[eid]["text"]).lower() for eid in ids):
            raise ValueError(f"Supporting quote for {skill!r} was not found verbatim in its cited evidence. Use an exact excerpt.")
        if skill.lower() not in {x.lower() for x in required}: raise ValueError(f"Matched skill {skill!r} is not in required_skills")
        accepted.append({"skill":skill,"evidence_ids":list(dict.fromkeys(ids)),"support_quote":quote})
    distinct={x["skill"].lower():x for x in accepted}
    gaps=[x for x in required if x.lower() not in distinct]
    skill_score=round(100*len(distinct)/len(required)) if required else None
    role=max(0,min(100,int(analysis.get("role_relevance",0))))
    overall=skill_score if skill_score is not None else role
    why=[]
    for item in analysis.get("why_fits",[])[:8]:
        if not isinstance(item,dict): raise ValueError("why_fits items need claim, evidence_ids, and exact support_quote")
        claim=str(item.get("claim","")).strip(); quote=str(item.get("support_quote","")).strip(); ids=item.get("evidence_ids",[])
        if not claim or not quote or not isinstance(ids,list) or not ids or any(eid not in all_ids for eid in ids):
            raise ValueError("Each why_fits claim needs exact supporting evidence IDs and a quote")
        if not any(re.sub(r"\s+"," ",quote).lower() in re.sub(r"\s+"," ",all_ids[eid]["text"]).lower() for eid in ids):
            raise ValueError(f"support_quote for fit claim {claim!r} was not found in cited evidence")
        why.append({"claim":claim[:500],"evidence_ids":list(dict.fromkeys(ids)),"support_quote":quote})
    prior=job.get("match",{})
    result={**prior,"overall":overall,"skills":skill_score,"job_skills":required,"matched_skills":[x["skill"] for x in distinct.values()],
      "matched_skill_evidence":list(distinct.values()),"potential_gaps":gaps,"title_relevance":role,
      "experience_relevance":max(0,min(100,int(analysis.get("experience_relevance",0)))),
      "industry_relevance":max(0,min(100,int(analysis.get("industry_relevance",0)))),
      "seniority_relevance":max(0,min(100,int(analysis.get("seniority_relevance",0)))),
      "why_fits":why,"match_method":"host-model with exact evidence quotes"}
    store.update_match(job_id,result)
    return {"job_id":job_id,"overall":overall,"skills":skill_score,"required_skills":required,
      "matched_skills":result["matched_skills"],"potential_gaps":gaps,"role_relevance":role,
      "why_fits":result["why_fits"],"match_method":result["match_method"]}

@mcp.tool()
def prepare_batch(job_ids: list[str]) -> dict[str,Any]:
    """Prepare compact tailoring briefs for up to five unique jobs selected by the user; does not generate documents or submit applications."""
    ids=list(dict.fromkeys(job_ids))
    if len(ids)>5: raise ValueError("A preparation batch is limited to five distinct jobs")
    return {"briefs":[_brief(jid,6,500) for jid in ids],"count":len(ids),"next":"Generate documents only for jobs the candidate selects; call tailoring_brief for its complete evidence."}

@mcp.tool()
def save_tailored_document(job_id: str, kind: str, content: str, evidence_ids: list[str]) -> dict[str,Any]:
    """Validate and export a host-model draft as DOCX/PDF. kind is resume or cover_letter. Supporting resume evidence IDs are required; numeric claims are checked against those snippets."""
    kind=kind.strip().lower()
    if kind not in {"resume","cover_letter"}: raise ValueError("kind must be resume or cover_letter")
    if len(content.strip())<100: raise ValueError("Draft is too short to save; revise it before exporting.")
    if len(content)>60000: raise ValueError("Draft exceeds the 60,000 character safety limit; condense it before exporting.")
    if len(evidence_ids)>100: raise ValueError("Use at most 100 evidence IDs")
    job=store.job(job_id)
    if not job: raise ValueError("Unknown job id")
    if not evidence_ids: raise ValueError("Cite at least one supporting evidence ID from tailoring_brief.")
    evidence=store.evidence(evidence_ids)
    if set(evidence_ids)!={x["id"] for x in evidence}: raise ValueError("One or more evidence IDs do not exist. Refresh tailoring_brief and retry.")
    for item in evidence:
        if item["verification"] not in {"verified","approved"}:
            raise ValueError(f"Evidence {item['id']} is unverified. Approve it before using it in an employer-facing document.")
        if kind=="resume" and item["visibility"] not in {"resume_cover_letter","resume_only"}:
            raise ValueError(f"Evidence {item['id']} is not approved for resumes.")
        if kind=="cover_letter" and item["visibility"] not in {"resume_cover_letter","cover_letter_only"}:
            raise ValueError(f"Evidence {item['id']} is not approved for cover letters.")
    evidence_text="\n".join(x["text"] for x in evidence)
    evidence_text+="\n"+" ".join(str(v) for k,v in store.profile().items() if k in {"name","email","phone","location","linkedin_url","github_url","website_url"})
    if kind=="cover_letter":
        words=len(re.findall(r"[\w‌]+(?:[’'-][\w‌]+)*",content,flags=re.UNICODE))
        if not 220<=words<=320: raise ValueError(f"Cover letter is {words} words; revise to 220–320 words and retry. No draft was saved.")
    unsupported=sorted(numbers(content)-numbers(evidence_text)-{str(__import__("datetime").date.today().year)})
    if unsupported: raise ValueError(f"Numeric claims are not found in the cited resume evidence: {unsupported[:12]}. Remove or substantiate them, then retry. No draft was saved.")
    score,qa=ats_estimate(content,job,kind); profile=store.profile(); candidate=profile.get("name") or "Candidate"
    chosen_language=profile.get("document_language","job")
    output_language=detect_language(job.get("description","")) if chosen_language=="job" else normalize_language(chosen_language)
    outdir=data_dir()/"documents"/job_id; docx,pdf=render_docs(content,kind,candidate,job["title"],outdir,output_language)
    did=uuid.uuid4().hex[:12]; store.save_document(did,job_id,kind,content,evidence_ids,score,docx,pdf)
    return {"document_id":did,"kind":kind,"ats_estimate":score,"ats_qa":qa,"output_language":output_language,
      "text_direction":"rtl" if output_language in {"fa","ar"} else "ltr","word_count":len(re.findall(r"[\w‌]+(?:[’'-][\w‌]+)*",content,flags=re.UNICODE)),
      "evidence_ids":evidence_ids,"source_files":sorted({x["source_name"] for x in evidence}),"docx_path":docx,"pdf_path":pdf,
      "integrity_note":"Numeric values were checked against cited resume snippets. This automated check cannot prove every paraphrase; review all factual claims before use."}

@mcp.tool()
def document_list(job_id: str) -> dict[str,Any]:
    """List saved tailored resume/cover letter versions and local export paths for a job."""
    if not store.job(job_id): raise ValueError("Unknown job id")
    return {"documents":store.documents(job_id)}

@mcp.tool()
def job_status_update(job_id: str, status: str) -> dict[str,Any]:
    """Manually update a job's tracking status: New, Viewed, Saved, Ignored, Planning to Apply, Applied, Interview, Rejected, Offer, Closed."""
    store.set_status(job_id,status); return {"job_id":job_id,"status":status}

@mcp.tool()
def job_status_history(job_id: str, page: int=1, page_size: int=25) -> dict[str,Any]:
    """Read the paginated manual status-change history for a saved job."""
    if not store.job(job_id): raise ValueError("Unknown job id")
    rows,total=store.status_history(job_id,page,page_size); size=max(1,min(100,page_size))
    return {"history":rows,"page":max(1,page),"page_size":size,"total":total,"total_pages":(total+size-1)//size}

def main() -> None:
    mcp.run()
