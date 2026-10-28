from pathlib import Path

import pytest

from career_compass_mcp.matching import eligibility, score_job, terms
from career_compass_mcp.documents import numbers, safe_slug
from career_compass_mcp.preferences import (detect_language, infer_mobility_support, infer_work_arrangement, normalize_language, normalize_mobility_support,
                                             normalize_work_arrangements)
from career_compass_mcp.sources import make_search_queries, _validate_public_url
from career_compass_mcp.store import Store


def test_matching_uses_all_resumes_and_title_is_separate():
    job={"title":"Data Analyst","description":"Required: SQL, Python, and Power BI dashboards."}
    result=score_job(job,["SQL analysis and reports.","Python programming for experiments."],["Product Manager"])
    assert result["overall"]==67
    assert result["matched_skills"]==["Python","SQL"]
    assert result["title_relevance"]==0


def test_matching_does_not_role_penalize_skill_coverage():
    job={"title":"Product Manager","description":"Need SQL, Python, and stakeholder management."}
    result=score_job(job,["SQL, Python, stakeholder management, data analytics"],["Data Analyst"])
    assert result["overall"]==100
    assert result["title_relevance"]==0


def test_country_and_remote_eligibility_is_conservative():
    assert eligibility({"location":"Remote - United States","remote":"remote"},["Spain"])=="ineligible"
    assert eligibility({"location":"Worldwide","remote":"remote"},["Spain"])=="likely eligible"
    assert eligibility({"location":"Remote","remote":"remote"},["Spain"])=="unknown"
    assert eligibility({"description":"Visa sponsorship available for qualified applicants"},["Spain"])=="unknown"


def test_search_queries_cover_every_target_title_and_board():
    titles=[f"Role {n}" for n in range(1,31)]
    queries=make_search_queries(titles,["Spain","Turkey"])
    assert len(queries)==78
    combined="\n".join(queries)
    assert all(title in combined for title in titles)
    assert "site:linkedin.com/jobs" in queries[0]
    assert any("site:ergodotisi.com" in query for query in queries)


def test_search_queries_include_localized_titles_and_optional_filters():
    queries=make_search_queries(["Data Analyst"],["España"],["hybrid","in_person"],["relocation"],["analista de datos","محلل بيانات"])
    assert len(queries)==26
    assert all("analista de datos" in query and "محلل بيانات" in query for query in queries)
    assert all('"hybrid"' in query and '"on-site"' in query and '"relocation assistance"' in query for query in queries)


def test_four_language_support_and_unicode_export_helpers():
    assert [normalize_language(x) for x in ["English","Farsi","Spanish","Arabic"]]==["en","fa","es","ar"]
    assert [detect_language(x) for x in ["Hello team", "سلام فارسی", "العمل عن بعد", "Experiencia con datos"]]==["en","fa","ar","es"]
    assert normalize_work_arrangements(["remoto","híbrido","presencial"])==["remote","hybrid","in_person"]
    assert normalize_mobility_support(["reubicación","رعاية التأشيرة"])==["relocation","visa_sponsorship"]
    assert safe_slug("پروژه مدیر محصول") == "پروژه_مدیر_محصول"
    assert numbers("درآمد ۴۰٪ و ١٢ پروژه") == {"40%","12"}
    assert "Data Analysis" in terms("Análisis de datos y SQL")
    assert "Data Analysis" in terms("تحلیل داده و SQL")
    assert "Product Management" in terms("إدارة المنتج")


def test_work_mode_and_country_detection_localized():
    assert eligibility({"location":"Remoto - España","remote":"unknown"},["Spain"])=="eligible"
    assert eligibility({"location":"هیبرید - آلمان","remote":"hybrid"},["ألمانيا"])=="eligible"


def test_profile_and_evidence_provenance(tmp_path: Path):
    db=Store(tmp_path/"test.sqlite3")
    db.update_profile({"target_titles":["Data Analyst"],"countries":["Spain"]})
    db.save_resume("r1","/private/a.pdf","a.pdf","SQL and Python experience.",["SQL experience.","Python experience."])
    assert db.profile()["target_titles"]==["Data Analyst"]
    assert {x["source_name"] for x in db.evidence()}=={"a.pdf"}
    assert all(x["verification"]=="verified" for x in db.evidence())
    item={"source":"test","external_id":"1","title":"Data Analyst","description":"SQL","eligibility":"eligible"}
    jid=db.upsert_job(item); assert db.job(jid)["title"]=="Data Analyst"
    assert db.jobs(page=1,page_size=1)[1]==1


def test_job_filters_apply_work_arrangement_and_mobility(tmp_path: Path):
    db=Store(tmp_path/"filters.sqlite3")
    db.upsert_job({"source":"test","external_id":"hybrid-relocation","title":"Hybrid Analyst","remote":"hybrid","eligibility":"eligible","mobility_support":["relocation"]})
    db.upsert_job({"source":"test","external_id":"remote-visa","title":"Remote Analyst","remote":"remote","eligibility":"eligible","mobility_support":["visa_sponsorship"]})
    db.upsert_job({"source":"test","external_id":"onsite","title":"Office Analyst","remote":"in_person","eligibility":"eligible"})
    jobs,total=db.jobs(work_arrangements=["hybrid","in_person"],mobility_support=["relocation"])
    assert total==2 and {job["title"] for job in jobs}=={"Hybrid Analyst","Office Analyst"}
    jobs,total=db.jobs(work_arrangements=["in_person"])
    assert total==1 and jobs[0]["title"]=="Office Analyst"
    jobs,total=db.jobs()
    assert total==3


def test_reject_private_resume_site_url():
    with pytest.raises(ValueError):
        _validate_public_url("http://127.0.0.1/admin")


def test_web_evidence_defaults_to_unverified_and_resets_when_page_changes(tmp_path: Path):
    db=Store(tmp_path/"evidence.sqlite3")
    db.save_web_evidence("web1","https://portfolio.example/projects","Projects","SQL project description")
    item=db.evidence(["web1"])[0]
    assert item["verification"]=="unverified"
    assert item["visibility"]=="matching_only"
    assert db.web_evidence_visibility(["web1"],"approved","resume_cover_letter")==1
    db.save_web_evidence("web1","https://portfolio.example/projects","Projects","SQL project description")
    assert db.evidence(["web1"])[0]["verification"]=="approved"
    db.save_web_evidence("web1","https://portfolio.example/projects","Projects","Changed claim: SQL, Python")
    assert db.evidence(["web1"])[0]["verification"]=="unverified"


def test_manual_job_status_history_is_recorded(tmp_path: Path):
    db=Store(tmp_path/"history.sqlite3")
    jid=db.upsert_job({"source":"test","external_id":"job1","title":"Role","eligibility":"eligible"})
    db.set_status(jid,"Saved")
    db.set_status(jid,"Applied")
    rows,total=db.status_history(jid)
    assert total==2
    assert rows[0]["new_status"]=="Applied"
    assert rows[1]["old_status"]=="New"



def test_source_cache_invalidates_when_search_criteria_change(tmp_path: Path):
    db=Store(tmp_path/"sources.sqlite3")
    assert db.source_is_due("Bing Search",3600,fingerprint="titles-a")
    db.mark_source_attempt("Bing Search",True,"titles-a")
    assert not db.source_is_due("Bing Search",3600,fingerprint="titles-a")
    assert db.source_is_due("Bing Search",3600,fingerprint="titles-b")


def test_work_arrangement_and_mobility_inference_in_supported_languages():
    assert infer_work_arrangement({"description":"Trabajo presencial en Madrid"})=="in_person"
    assert infer_work_arrangement({"description":"العمل عن بعد"})=="remote"
    assert infer_work_arrangement({"description":"فرصة عمل بنظام هجين"})=="hybrid"
    assert infer_work_arrangement({"description":"محل کار با امکان کار در خانه یا دفتر"}) in {"other","unknown"}
    assert "relocation" in infer_mobility_support({"description":"Ayuda de reubicación disponible"})
    assert "visa_sponsorship" in infer_mobility_support({"description":"رعاية التأشيرة متاحة"})


def test_existing_database_schema_is_migrated_for_new_preferences(tmp_path: Path):
    import sqlite3
    db_path=tmp_path/"old.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, title TEXT NOT NULL, company TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '', apply_url TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '', posted_at TEXT NOT NULL DEFAULT '', remote TEXT NOT NULL DEFAULT 'unknown', eligibility TEXT NOT NULL DEFAULT 'unknown', match_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'New', fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(source,external_id))")
        db.execute("CREATE TABLE source_sync(source TEXT PRIMARY KEY,last_attempt REAL NOT NULL DEFAULT 0,last_success REAL NOT NULL DEFAULT 0)")
    Store(db_path)
    with sqlite3.connect(db_path) as db:
        job_columns={row[1] for row in db.execute("PRAGMA table_info(jobs)")}
        source_columns={row[1] for row in db.execute("PRAGMA table_info(source_sync)")}
    assert "mobility" in job_columns
    assert "fingerprint" in source_columns
