from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

TIMEOUT=httpx.Timeout(20.0,connect=8.0)
HEADERS={"User-Agent":"ResumeToRoleMCP/0.1 (+https://modelcontextprotocol.io/)"}

def plain(value: Any) -> str:
    if value is None: return ""
    return re.sub(r"\s+"," ",BeautifulSoup(unescape(str(value)),"html.parser").get_text(" ",strip=True)).strip()

def base(src: str, ext: Any, title: Any, company: Any, location: Any, desc: Any,
         apply: Any, url: Any, posted: Any="", remote: str="unknown", eligibility: str="unknown") -> dict[str,Any]:
    return {"source":src,"external_id":str(ext or url or title),"title":plain(title)[:300],"company":plain(company)[:240],
            "location":plain(location)[:500],"description":plain(desc)[:30000],"apply_url":str(apply or ""),
            "source_url":str(url or apply or ""),"posted_at":str(posted or ""),"remote":remote,"eligibility":eligibility}

async def get(c: httpx.AsyncClient, url: str, params: dict|None=None):
    r=await c.get(url,params=params,headers=HEADERS); r.raise_for_status(); return r

async def search_public_feeds(queries: list[str], countries: list[str], limit: int=100, include_bing: bool=True,
                              sources_to_fetch: list[str]|None=None,
                              work_arrangements: list[str]|None=None,
                              mobility_support: list[str]|None=None):
    limit=max(10,min(200,limit)); queries=[q.strip() for q in queries if q and q.strip()][:8] or ["product manager","data analyst"]
    # Reuse broad feeds once per run; only search endpoints receive per-query requests.
    phrases=[]
    for q in queries:
        phrases.extend(x.strip().strip('"') for x in re.split(r"\s+OR\s+",q,flags=re.I) if x.strip())
    phrases=list(dict.fromkeys(phrases))[:32]
    country=" ".join(countries[:12]); tasks=[]; partial_errors={}
    def relevant(text):
        low=text.lower()
        return any(term.lower() in low for term in phrases)
    async def broad_remoteok():
        async with httpx.AsyncClient(timeout=TIMEOUT) as c: data=(await get(c,"https://remoteok.com/api")).json()
        return [base("Remote OK",x.get("id"),x.get("position"),x.get("company"),x.get("location"),x.get("description"),x.get("apply_url"),x.get("url"),x.get("date"),"remote") for x in data if isinstance(x,dict) and x.get("position") and relevant(str(x.get("position",""))+" "+str(x.get("tags",""))+" "+plain(x.get("description")))][:limit]
    async def broad_remotive():
        async with httpx.AsyncClient(timeout=TIMEOUT) as c: data=(await get(c,"https://remotive.com/api/remote-jobs",{"limit":200})).json().get("jobs",[])
        return [base("Remotive",x.get("id"),x.get("title"),x.get("company_name"),x.get("candidate_required_location"),x.get("description"),None,x.get("url"),x.get("publication_date"),"remote") for x in data if relevant(str(x.get("title",""))+" "+str(x.get("tags",""))+" "+plain(x.get("description")))][:limit]
    async def broad_arbeitnow():
        async with httpx.AsyncClient(timeout=TIMEOUT) as c: data=(await get(c,"https://www.arbeitnow.com/api/job-board-api")).json().get("data",[])
        return [base("Arbeitnow",x.get("slug") or x.get("url"),x.get("title"),x.get("company_name"),x.get("location"),x.get("description"),None,x.get("url"),x.get("created_at"),"remote" if x.get("remote") else "unknown") for x in data if relevant(str(x.get("title",""))+" "+plain(x.get("description")))][:limit]
    async def broad_jobicy():
        async with httpx.AsyncClient(timeout=TIMEOUT) as c: data=(await get(c,"https://jobicy.com/api/jobs",{"count":min(200,limit)})).json().get("jobs",[])
        return [base("Jobicy",x.get("id"),x.get("title"),x.get("companyName"),x.get("jobGeo"),x.get("jobDescription"),None,x.get("url"),x.get("pubDate"),"remote") for x in data if relevant(str(x.get("title",""))+" "+plain(x.get("jobDescription")))][:limit]
    async def broad_wwr():
        async with httpx.AsyncClient(timeout=TIMEOUT) as c: r=await get(c,"https://weworkremotely.com/remote-jobs.rss")
        root=ET.fromstring(r.text); out=[]
        for x in root.findall(".//item"):
            title=x.findtext("title",""); desc=x.findtext("description","")
            if not relevant(title+" "+plain(desc)): continue
            url=x.findtext("link",""); out.append(base("We Work Remotely",url,title,"",x.findtext("category","Remote"),desc,None,url,x.findtext("pubDate"),"remote"))
        return out[:limit]
    async def himalayas(q):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c: data=(await get(c,"https://himalayas.app/jobs/api/search",{"q":q,"sort":"recent","page":1})).json().get("jobs",[])
        out=[]
        for x in data[:limit]:
            restrictions=x.get("locationRestrictions") or []; names=[v.get("name") if isinstance(v,dict) else str(v) for v in restrictions]
            loc=", ".join(names) or "Worldwide"; eligible="unknown"
            if countries and names: eligible="eligible" if any(any(cn.lower() in n.lower() or n.lower() in cn.lower() for cn in countries) for n in names) else "ineligible"
            out.append(base("Himalayas",x.get("guid"),x.get("title"),x.get("companyName"),loc,x.get("description") or x.get("excerpt"),x.get("applicationLink"),x.get("applicationLink"),x.get("pubDate"),"remote",eligible))
        return out
    async def bing():
        if not include_bing:return []
        groups=[phrases[i:i+16] for i in range(0,len(phrases),16)] or [["jobs"]]
        criteria=_preference_query(work_arrangements,mobility_support); out=[]
        async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=True) as c:
            async def fetch(group):
                query_terms=" OR ".join(f'"{x}"' for x in group)
                query=f'({query_terms}) {country} (jobs OR careers OR hiring) {criteria}'.strip()
                response=await get(c,"https://www.bing.com/search",{"format":"rss","q":query,"count":limit})
                return ET.fromstring(response.text)
            results=await asyncio.gather(*(fetch(group) for group in groups),return_exceptions=True)
        failures=0
        for result in results:
            if isinstance(result,BaseException): failures+=1; continue
            for x in result.findall(".//item"):
                title=x.findtext("title",""); url=x.findtext("link",""); desc=plain(x.findtext("description",""))
                if url.startswith("https://") and "bing.com" not in urlparse(url).netloc.lower():
                    out.append(base("Bing Search",url,title,"","",desc,None,url,x.findtext("pubDate")))
        if failures==len(results): raise RuntimeError("All Bing localized-title query batches failed")
        if failures: partial_errors["Bing Search"]=f"{failures} of {len(results)} localized-title query batches failed"
        unique={item["source_url"]:item for item in reversed(out)}
        return list(unique.values())[:limit*len(groups)]
    selected=set(sources_to_fetch or ["Remote OK","Remotive","Arbeitnow","Jobicy","We Work Remotely","Bing Search","Himalayas"])
    for name,fn in [("Remote OK",broad_remoteok),("Remotive",broad_remotive),("Arbeitnow",broad_arbeitnow),
                    ("Jobicy",broad_jobicy),("We Work Remotely",broad_wwr),("Bing Search",bing)]:
        if name in selected:tasks.append((name,fn()))
    if "Himalayas" in selected:
        for q in queries:tasks.append(("Himalayas",himalayas(q)))
    results=await asyncio.gather(*(t for _,t in tasks),return_exceptions=True); jobs=[]; errors=dict(partial_errors)
    for (name,_),result in zip(tasks,results):
        if isinstance(result,BaseException):errors[name]=str(result)[:300]
        else:jobs.extend(result)
    return jobs,errors

async def search_company_boards(board_type: str, board_ids: list[str], limit: int=100):
    if board_type not in {"greenhouse","lever","ashby","smartrecruiters"}: raise ValueError("board_type must be greenhouse, lever, ashby, or smartrecruiters")
    async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=True) as c:
        async def fetch(slug):
            slug=slug.strip()
            if not slug or len(slug)>120 or re.search(r"[^a-zA-Z0-9._-]",slug): raise ValueError("Invalid board identifier")
            if board_type=="greenhouse":
                data=(await get(c,f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",{"content":"true"})).json().get("jobs",[])
                return [base("Greenhouse",x.get("id"),x.get("title"),x.get("company_name") or slug,", ".join(i.get("location","") for i in x.get("offices",[]) if isinstance(i,dict)),x.get("content"),None,x.get("absolute_url"),x.get("updated_at")) for x in data[:limit]]
            if board_type=="lever":
                data=(await get(c,f"https://api.lever.co/v0/postings/{slug}",{"mode":"json","limit":limit})).json()
                return [base("Lever",x.get("id"),x.get("text"),slug,x.get("categories",{}).get("location"),x.get("descriptionPlain") or x.get("description"),x.get("applyUrl"),x.get("hostedUrl"),x.get("createdAt"),x.get("workplaceType","unknown")) for x in data[:limit]]
            if board_type=="ashby":
                data=(await get(c,f"https://api.ashbyhq.com/posting-api/job-board/{slug}")).json()
                return [base("Ashby",x.get("id") or x.get("jobUrl"),x.get("title"),x.get("companyName") or slug,x.get("location"),x.get("descriptionPlain") or x.get("description"),x.get("applyUrl"),x.get("jobUrl"),x.get("publishedAt"),"remote" if x.get("isRemote") else "unknown") for x in data.get("jobs",[])[:limit]]
            data=(await get(c,f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",{"limit":limit})).json().get("content",[]); out=[]
            for x in data:
                loc=x.get("location") or {}; location=", ".join(filter(None,[loc.get("city"),loc.get("region"),loc.get("country")])); ref=x.get("ref",""); full={}
                if ref:
                    try: full=(await get(c,ref)).json()
                    except Exception: pass
                ad=full.get("jobAd") or {}; apply=full.get("applyUrl") or x.get("applyUrl")
                job_page=full.get("jobAdUrl") or f"https://jobs.smartrecruiters.com/{slug}/{x.get('id','')}"
                out.append(base("SmartRecruiters",x.get("id"),x.get("name"),slug,location,ad.get("jobDescription"),apply,job_page,full.get("releasedDate")))
            return out
        results=await asyncio.gather(*(fetch(x) for x in board_ids[:40]),return_exceptions=True)
    jobs=[]; errors={}
    for slug,result in zip(board_ids[:40],results):
        if isinstance(result,BaseException): errors[f"{board_type}:{slug}"]=str(result)[:250]
        else: jobs.extend(result)
    return jobs,errors

ARRANGEMENT_QUERY_TERMS = {
    "remote": ['"remote"', '"fully remote"', '"teletrabajo"', '"trabajo remoto"', '"عن بعد"', '"دورکاری"'],
    "hybrid": ['"hybrid"', '"híbrido"', '"hibrido"', '"هجين"', '"ترکیبی"'],
    "in_person": ['"on-site"', '"in person"', '"presencial"', '"حضوري"', '"حضوری"'],
    "other": ['"field-based"', '"field work"', '"flexible location"', '"مرن الموقع"', '"محل کار منعطف"'],
}
MOBILITY_QUERY_TERMS = {
    "relocation": ['"relocation assistance"', '"relocation support"', '"ayuda de reubicación"', '"دعم الانتقال"', '"حمایت جابه‌جایی"'],
    "visa_sponsorship": ['"visa sponsorship"', '"patrocinio de visa"', '"رعاية التأشيرة"', '"حمایت ویزا"'],
}


def _preference_query(work_arrangements: list[str] | None, mobility_support: list[str] | None) -> str:
    terms=[]
    for values, dictionary in ((work_arrangements or [], ARRANGEMENT_QUERY_TERMS),
                               (mobility_support or [], MOBILITY_QUERY_TERMS)):
        for value in values:
            terms.extend(dictionary.get(str(value).strip().lower(), []))
    return "("+" OR ".join(dict.fromkeys(terms))+")" if terms else ""


def make_search_queries(titles: list[str], countries: list[str],
                        work_arrangements: list[str] | None = None,
                        mobility_support: list[str] | None = None,
                        localized_titles: list[str] | None = None) -> list[str]:
    domains=["linkedin.com/jobs","indeed.com/viewjob","glassdoor.com/job-listing","wellfound.com/jobs",
      "ycombinator.com/jobs","eures.europa.eu","welcome-to-the-jungle.com/jobs","remoteok.com",
      "remotive.com","weworkremotely.com","workingnomads.com/jobs","jobgether.com","himalayas.app/jobs",
      "arbeitnow.com","jobicy.com","landing.jobs","relocate.me","nofluffjobs.com","stepstone.com",
      "kariyer.net","techcareer.net","infojobs.net","tecnoempleo.com","ergodotisi.com","workinfinland.com","workindenmark.dk"]
    title_terms=list(dict.fromkeys(str(x).strip() for x in [*(titles or []),*(localized_titles or [])] if str(x).strip()))[:128]
    if not title_terms: title_terms=['product manager','data analyst']
    # Keep queries small while ensuring every configured role and supplied translation is searched.
    groups=[title_terms[i:i+12] for i in range(0,len(title_terms),12)]
    cq=" OR ".join(f'"{x}"' for x in countries[:10]) or "Europe OR EMEA OR worldwide"
    criteria=_preference_query(work_arrangements,mobility_support)
    queries=[]
    for domain in domains:
        for group in groups:
            tq=" OR ".join(f'"{x[:100]}"' for x in group)
            queries.append(f'({tq}) ({cq} OR Europe OR EMEA OR worldwide) (job OR vacancy OR career) {criteria} site:{domain}'.replace("  "," "))
    return queries

def _validate_public_url(url: str) -> str:
    p=urlparse(url)
    if p.scheme not in {"http","https"} or not p.hostname or p.username or p.password:
        raise ValueError("Only public HTTP/HTTPS website URLs are allowed")
    if p.port not in {None,80,443}: raise ValueError("Nonstandard website ports are not allowed")
    host=p.hostname.lower()
    if host.endswith((".localhost",".local",".internal")) or host in {"localhost","metadata.google.internal"}:
        raise ValueError("Local or metadata endpoints are not allowed")
    try:
        resolved=socket.getaddrinfo(host,p.port or (443 if p.scheme=="https" else 80),type=socket.SOCK_STREAM)
        if not resolved: raise ValueError("Website host did not resolve")
        if any(not ipaddress.ip_address(row[4][0]).is_global for row in resolved):
            raise ValueError("Website URL resolves to a private or reserved address")
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve website host: {e}")
    return url

async def crawl_career_sites(urls: list[str], max_pages_per_site: int=6) -> tuple[list[dict[str,str]],list[dict[str,str]]]:
    """Fetch only explicitly provided public websites and a few relevant same-host portfolio links."""
    pages=[]; errors=[]
    async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=False) as c:
        for original in urls[:12]:
            try:
                root=_validate_public_url(original); root_host=urlparse(root).hostname
                queue=[root]; visited=set()
                while queue and len(visited)<max(1,min(8,max_pages_per_site)):
                    url=_validate_public_url(queue.pop(0))
                    if url in visited: continue
                    visited.add(url)
                    response=None; current=url
                    for _ in range(4):
                        _validate_public_url(current)
                        response=await c.get(current,headers=HEADERS)
                        if response.status_code in {301,302,303,307,308} and response.headers.get("location"):
                            current=urljoin(current,response.headers["location"]); continue
                        break
                    if response is None or response.status_code>=400:
                        raise ValueError(f"HTTP {response.status_code if response else 'error'}")
                    if len(response.content)>2_000_000: raise ValueError("Page exceeds 2 MB")
                    if "text/html" not in response.headers.get("content-type","").lower(): continue
                    soup=BeautifulSoup(response.text,"html.parser")
                    for node in soup(["script","style","noscript","svg","nav","footer"]): node.decompose()
                    title=(soup.title.get_text(" ",strip=True) if soup.title else "")[:180]
                    text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True))[:18000]
                    if text: pages.append({"url":str(response.url),"title":title,"text":text})
                    if len(visited)==1:
                        for a in soup.find_all("a",href=True):
                            link=urljoin(str(response.url),a["href"]); parsed=urlparse(link)
                            label=(a.get_text(" ",strip=True)+" "+parsed.path).lower()
                            if parsed.hostname==root_host and any(k in label for k in ("project","portfolio","case-stud","work","product","about","experience","repository","repo")):
                                if link not in visited and link not in queue: queue.append(link)

            except Exception as e:
                errors.append({"url":original,"error":str(e)[:240]})
    return pages,errors
