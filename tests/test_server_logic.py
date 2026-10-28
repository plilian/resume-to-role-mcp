import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

from career_compass_mcp.store import Store


def load_server(monkeypatch, data_home):
    monkeypatch.setenv("CAREER_COMPASS_HOME",str(data_home))
    if "mcp" not in sys.modules and importlib.util.find_spec("mcp") is None:
        package=types.ModuleType("mcp"); package.__path__=[]
        submodule=types.ModuleType("mcp.server")
        class FakeMCPServer:
            def __init__(self,name): self.name=name
            def tool(self): return lambda fn: fn
            def run(self): raise RuntimeError("The test stub does not run stdio")
        submodule.MCPServer=FakeMCPServer
        sys.modules["mcp"]=package; sys.modules["mcp.server"]=submodule
    sys.modules.pop("career_compass_mcp.server",None)
    return importlib.import_module("career_compass_mcp.server")


def test_host_semantic_match_requires_exact_resume_quotes(tmp_path,monkeypatch):
    server=load_server(monkeypatch,tmp_path)
    server.store=Store(tmp_path/"career.sqlite3")
    server.store.save_resume("r1","/chosen/resume.txt","Data CV.txt","Used SQL to analyze customer data. Built Python automation.",[
        "Used SQL to analyze customer data.","Built Python automation."])
    jid=server.store.upsert_job({"source":"test","external_id":"m1","title":"Product Analyst","description":"SQL, Python, and Tableau"})
    data={"required_skills":["SQL","Python","Tableau"],"matched_skills":[
        {"skill":"SQL","evidence_ids":["r1-e000"],"support_quote":"Used SQL to analyze customer data."},
        {"skill":"Python","evidence_ids":["r1-e001"],"support_quote":"Built Python automation."}],
        "role_relevance":0,"why_fits":[{"claim":"The candidate has relevant analysis experience.","evidence_ids":["r1-e000"],"support_quote":"Used SQL to analyze customer data."}]}
    result=server.job_match_update(jid,json.dumps(data))
    assert result["overall"]==67
    assert result["role_relevance"]==0
    assert result["potential_gaps"]==["Tableau"]
    data["matched_skills"][0]["support_quote"]="Invented experience with SQL"
    with pytest.raises(ValueError,match="not found verbatim"):
        server.job_match_update(jid,json.dumps(data))


def test_document_gate_and_filename_export(tmp_path,monkeypatch):
    server=load_server(monkeypatch,tmp_path)
    server.store=Store(tmp_path/"career.sqlite3")
    server.store.update_profile({"name":"Test Candidate"})
    server.store.save_resume("r1","/chosen/resume.txt","Resume.txt","Used SQL and Python for product analysis.",[
        "Used SQL and Python for product analysis."])
    jid=server.store.upsert_job({"source":"test","external_id":"d1","title":"Data Analyst","description":"SQL and Python required"})
    words="I used SQL and Python for product analysis, and I can explain how this experience supports the specific responsibilities of this role."
    letter="Dear Hiring Team,\n\n"+((words+" ")*12)+"\nSincerely,\nTest Candidate"
    while len(letter.split())<220: letter+=words+" "
    letter=" ".join(letter.split()[:320])
    with pytest.raises(ValueError,match="Numeric claims"):
        server.save_tailored_document(jid,"cover_letter",letter+" I improved revenue by 40%.",["r1-e000"])
    resume="# Test Candidate\n\nSUMMARY\nData analyst experienced in SQL and Python.\n\nSKILLS\nSQL, Python\n\nEXPERIENCE\nUsed SQL and Python for product analysis.\n\nEDUCATION\nBachelor's degree."
    result=server.save_tailored_document(jid,"resume",resume,["r1-e000"])
    assert result["ats_estimate"]>=0
    assert result["docx_path"].endswith("Test_Candidate_Data_Analyst_2026.docx")
    assert result["pdf_path"].endswith("Test_Candidate_Data_Analyst_2026.pdf")



def test_profile_language_and_optional_work_filters_flow_to_search_and_list(tmp_path,monkeypatch):
    server=load_server(monkeypatch,tmp_path)
    server.store=Store(tmp_path/"profile.sqlite3")
    updated=server.profile_update(json.dumps({
        "preferred_language":"فارسی", "document_language":"Arabic", "search_languages":["Spanish","ar"],
        "target_titles":["Data Analyst"],"countries":["España"],
        "work_arrangements":["híbrido","presencial"],"mobility_support":["reubicación"]
    },ensure_ascii=False))
    assert updated["preferred_language"]=="fa"
    assert updated["document_language"]=="ar"
    assert updated["search_languages"]==["es","ar"]
    assert updated["work_arrangements"]==["hybrid","in_person"]
    assert updated["mobility_support"]==["relocation"]
    query=server.source_search_queries(localized_titles=["analista de datos","محلل بيانات"])
    assert "analista de datos" in query["queries"][0]["query"]
    assert '"hybrid"' in query["queries"][0]["query"]
    assert '"relocation assistance"' in query["queries"][0]["query"]
    server.store.upsert_job({"source":"test","external_id":"1","title":"Hybrid Analyst","remote":"hybrid","eligibility":"eligible","mobility_support":["relocation"]})
    server.store.upsert_job({"source":"test","external_id":"2","title":"Remote Analyst","remote":"remote","eligibility":"eligible","mobility_support":["relocation"]})
    result=server.job_list()
    assert result["total"]==2
    assert {job["title"] for job in result["jobs"]}=={"Hybrid Analyst","Remote Analyst"}
    assert result["work_arrangements_filter"]==["hybrid","in_person"]


def test_profile_rejects_unsupported_languages(tmp_path,monkeypatch):
    server=load_server(monkeypatch,tmp_path)
    server.store=Store(tmp_path/"invalid-language.sqlite3")
    with pytest.raises(ValueError,match="Language must be one of"):
        server.profile_update(json.dumps({"preferred_language":"German"}))


@pytest.mark.parametrize("language,name,title",[("fa","پارسا لیلیان","مدیر محصول"),("ar","بارسا ليليان","مدير منتج")])
def test_rtl_documents_export_unicode_docx_and_pdf(language,name,title,tmp_path,monkeypatch):
    from zipfile import ZipFile
    from pypdf import PdfReader
    server=load_server(monkeypatch,tmp_path)
    server.store=Store(tmp_path/"rtl.sqlite3")
    server.store.update_profile({"name":name,"document_language":language})
    evidence="مدیریت محصول، تحلیل داده و همکاری با تیم‌های چندرشته‌ای در پروژه‌های نرم‌افزاری."
    server.store.save_resume("rtl1","/selected/resume.txt","رزومه.txt",evidence,[evidence])
    jid=server.store.upsert_job({"source":"test","external_id":language,"title":title,"description":"متطلبات المنتج وتحليل البيانات"})
    content=f"# {name}\n\n## خلاصه\n{evidence}\n\n## مهارت‌ها\nSQL، مدیریت محصول، تحلیل داده\n\n## تجربه\n{evidence}\n\n## تحصیلات\nکارشناسی"
    result=server.save_tailored_document(jid,"resume",content,["rtl1-e000"])
    assert result["output_language"]==language and result["text_direction"]=="rtl"
    assert name.replace(" ","_") in Path(result["docx_path"]).name and title.replace(" ","_") in Path(result["docx_path"]).name
    with ZipFile(result["docx_path"]) as docx:
        xml=docx.read("word/document.xml").decode("utf-8")
        assert "<w:bidi" in xml
        assert name in xml
    pdf=PdfReader(result["pdf_path"])
    assert len(pdf.pages)==1
    assert pdf.pages[0].extract_text().strip()



def test_discover_jobs_passes_locale_and_arrangement_preferences_to_feeds(tmp_path,monkeypatch):
    import asyncio
    server=load_server(monkeypatch,tmp_path)
    server.store=Store(tmp_path/"discovery.sqlite3")
    server.profile_update(json.dumps({"target_titles":["Data Analyst"],"countries":["España"],
      "search_languages":["es","fa"],"work_arrangements":["presencial"],"mobility_support":["relocation"]}))
    captured={}
    async def fake_search(queries,countries,limit,include_bing,sources,arrangements,mobility):
        captured.update(queries=queries,countries=countries,sources=sources,arrangements=arrangements,mobility=mobility)
        return [],{}
    server.search_public_feeds=fake_search
    result=asyncio.run(server.discover_jobs(queries=["analista de datos OR تحلیل داده"]))
    assert captured["queries"]==["analista de datos OR تحلیل داده"]
    assert captured["countries"]==["España"]
    assert captured["sources"]==["Bing Search"]
    assert captured["arrangements"]==["in_person"]
    assert captured["mobility"]==["relocation"]
    assert result["jobs_stored"]==0


def test_spanish_resume_export_uses_localized_ats_headings(tmp_path,monkeypatch):
    from pypdf import PdfReader
    from career_compass_mcp.matching import ats_estimate
    from career_compass_mcp.documents import render_docs
    content="Resumen\nExperiencia\nHabilidades\nEducaci\u00f3n\nAnalista de datos con SQL y Python."
    job={"title":"Analista de Datos","description":"An\u00e1lisis de datos, SQL y Python requeridos."}
    score,qa=ats_estimate(content,job,"resume")
    assert qa["format_score"]==100
    assert {"Data Analysis","SQL","Python"}<=set(qa["keywords_found"])
    docx,pdf=render_docs(content,"resume","Demo Candidate","Analista de Datos",tmp_path,"es")
    assert Path(docx).exists() and "Analista_de_Datos" in Path(docx).name
    assert len(PdfReader(pdf).pages)==1
