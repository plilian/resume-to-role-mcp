from __future__ import annotations

import json
import os
import platform
import sqlite3
import time
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    override = os.environ.get("CAREER_COMPASS_HOME")
    if override:
        root = Path(override).expanduser()
    elif platform.system() == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "CareerCompassMCP"
    elif platform.system() == "Darwin":
        root = Path.home() / "Library/Application Support/CareerCompassMCP"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "career-compass-mcp"
    root.mkdir(parents=True, exist_ok=True)
    return root


class Store:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or data_dir() / "career_compass.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL DEFAULT '{}');
            INSERT OR IGNORE INTO profile(id,data) VALUES(1,'{}');
            CREATE TABLE IF NOT EXISTS resumes(
              id TEXT PRIMARY KEY, path TEXT NOT NULL, name TEXT NOT NULL, text TEXT NOT NULL,
              imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS evidence(
              id TEXT PRIMARY KEY, resume_id TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
              ordinal INTEGER NOT NULL, text TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS web_evidence(
              id TEXT PRIMARY KEY, url TEXT NOT NULL, page_title TEXT NOT NULL DEFAULT '', text TEXT NOT NULL,
              verification TEXT NOT NULL DEFAULT 'unverified', visibility TEXT NOT NULL DEFAULT 'matching_only',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
              title TEXT NOT NULL, company TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '', apply_url TEXT NOT NULL DEFAULT '',
              source_url TEXT NOT NULL DEFAULT '', posted_at TEXT NOT NULL DEFAULT '',
              remote TEXT NOT NULL DEFAULT 'unknown', eligibility TEXT NOT NULL DEFAULT 'unknown', mobility TEXT NOT NULL DEFAULT '[]',
              match_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'New',
              fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(source,external_id));
            CREATE TABLE IF NOT EXISTS status_history(
              id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              old_status TEXT NOT NULL, new_status TEXT NOT NULL, changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS source_sync(
              source TEXT PRIMARY KEY, last_attempt REAL NOT NULL DEFAULT 0, last_success REAL NOT NULL DEFAULT 0,
              fingerprint TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS documents(
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              kind TEXT NOT NULL, content TEXT NOT NULL, evidence_ids TEXT NOT NULL,
              ats_score INTEGER NOT NULL, path_docx TEXT NOT NULL DEFAULT '', path_pdf TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "mobility" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN mobility TEXT NOT NULL DEFAULT '[]'")
            sync_columns={row[1] for row in db.execute("PRAGMA table_info(source_sync)")}
            if "fingerprint" not in sync_columns:
                db.execute("ALTER TABLE source_sync ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def profile(self) -> dict[str, Any]:
        with self.connect() as db:
            return json.loads(db.execute("SELECT data FROM profile WHERE id=1").fetchone()["data"] or "{}")

    def update_profile(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {"name", "email", "phone", "location", "linkedin_url", "github_url", "website_url", "evidence_sources", "resume_roots",
                   "target_titles", "countries", "remote_preferences", "work_arrangements", "mobility_support",
                   "preferred_language", "document_language", "search_languages", "seniority", "languages", "notes"}
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(f"Unknown profile fields: {', '.join(sorted(unknown))}")
        current = self.profile()
        current.update(patch)
        with self.connect() as db:
            db.execute("UPDATE profile SET data=? WHERE id=1", (json.dumps(current, ensure_ascii=False),))
        return current

    def save_resume(self, rid: str, path: str, name: str, text: str, chunks: list[str]) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO resumes(id,path,name,text) VALUES(?,?,?,?)", (rid,path,name,text))
            db.execute("DELETE FROM evidence WHERE resume_id=?", (rid,))
            db.executemany("INSERT INTO evidence(id,resume_id,ordinal,text) VALUES(?,?,?,?)",
                           [(f"{rid}-e{i:03d}",rid,i,x) for i,x in enumerate(chunks)])

    def resumes(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(x) for x in db.execute("SELECT id,path,name,length(text) AS chars,imported_at FROM resumes ORDER BY name")]

    def all_resume_text(self) -> list[str]:
        with self.connect() as db:
            return [x[0] for x in db.execute("SELECT text FROM resumes ORDER BY name")]

    def all_candidate_text(self) -> list[str]:
        with self.connect() as db:
            a=[x[0] for x in db.execute("SELECT text FROM resumes")]
            b=[x[0] for x in db.execute("SELECT text FROM web_evidence WHERE visibility!='ignore'")]
            return a+b

    def evidence(self, ids: list[str] | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if ids is not None:
                if not ids:
                    return []
                marks = ",".join("?" for _ in ids)
                rows = db.execute(f"SELECT e.id,e.text,r.name AS source_name,'verified' AS verification,'resume_cover_letter' AS visibility FROM evidence e JOIN resumes r ON r.id=e.resume_id WHERE e.id IN ({marks})", ids).fetchall()
                web = db.execute(f"SELECT id,text,url AS source_name,verification,visibility FROM web_evidence WHERE id IN ({marks})", ids).fetchall()
                return [dict(x) for x in list(rows)+list(web)]
            else:
                rows = db.execute("SELECT e.id,e.text,r.name AS source_name,'verified' AS verification,'resume_cover_letter' AS visibility FROM evidence e JOIN resumes r ON r.id=e.resume_id ORDER BY r.name,e.ordinal").fetchall()
                web = db.execute("SELECT id,text,url AS source_name,verification,visibility FROM web_evidence ORDER BY created_at DESC").fetchall()
                return [dict(x) for x in list(rows)+list(web)]

    def save_web_evidence(self, eid: str, url: str, title: str, text: str) -> None:
        with self.connect() as db:
            row=db.execute("SELECT text,verification,visibility FROM web_evidence WHERE id=?",(eid,)).fetchone()
            if row and row["text"]==text:
                db.execute("UPDATE web_evidence SET page_title=? WHERE id=?",(title,eid))
            elif row:
                db.execute("UPDATE web_evidence SET url=?,page_title=?,text=?,verification='unverified',visibility='matching_only' WHERE id=?",
                           (url,title,text,eid))
            else:
                db.execute("INSERT INTO web_evidence(id,url,page_title,text,verification,visibility) VALUES(?,?,?,?,'unverified','matching_only')",
                           (eid,url,title,text))

    def web_evidence_visibility(self, ids: list[str], verification: str, visibility: str) -> int:
        with self.connect() as db:
            count=0
            for eid in ids:
                cur=db.execute("UPDATE web_evidence SET verification=?,visibility=? WHERE id=?",(verification,visibility,eid))
                count+=cur.rowcount
            return count

    def upsert_job(self, item: dict[str, Any]) -> str:
        import hashlib
        src, ext = item["source"], str(item["external_id"])
        jid = hashlib.sha1(f"{src}:{ext}".encode()).hexdigest()[:16]
        with self.connect() as db:
            db.execute("""INSERT INTO jobs(id,source,external_id,title,company,location,description,apply_url,source_url,
              posted_at,remote,eligibility,mobility,match_json,fetched_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
              ON CONFLICT(source,external_id) DO UPDATE SET title=excluded.title,company=excluded.company,
              location=excluded.location,description=excluded.description,apply_url=excluded.apply_url,
              source_url=excluded.source_url,posted_at=excluded.posted_at,remote=excluded.remote,
              eligibility=excluded.eligibility,mobility=excluded.mobility,match_json=excluded.match_json,fetched_at=CURRENT_TIMESTAMP""",
              (jid,src,ext,item.get("title",""),item.get("company",""),item.get("location",""),
               item.get("description",""),item.get("apply_url",""),item.get("source_url",""),
               item.get("posted_at",""),item.get("remote","unknown"),item.get("eligibility","unknown"),
               json.dumps(item.get("mobility_support",[]),ensure_ascii=False),
               json.dumps(item.get("match",{}),ensure_ascii=False)))
        return jid

    def jobs(self, page: int = 1, page_size: int = 25, status: str = "", eligible_only: bool = True,
             work_arrangements: list[str] | None = None,
             mobility_support: list[str] | None = None) -> tuple[list[dict[str, Any]],int]:
        page=max(1,page); page_size=max(1,min(100,page_size))
        conditions=[]; args=[]
        if status: conditions.append("status=?"); args.append(status)
        if eligible_only: conditions.append("eligibility IN ('eligible','likely eligible','relocation available','sponsorship available')")
        arrangements={str(x).lower().strip() for x in (work_arrangements or [])}
        support={str(x).lower().strip() for x in (mobility_support or [])}
        preference_conditions=[]
        for value in ("remote", "hybrid", "in_person"):
            if value in arrangements:
                preference_conditions.append("lower(remote)=?"); args.append(value)
        if "other" in arrangements:
            preference_conditions.append("lower(remote)='other'")
        for value in ("relocation", "visa_sponsorship"):
            if value in support:
                preference_conditions.append("lower(mobility) LIKE ?"); args.append(f'%"{value}"%')
        if preference_conditions: conditions.append("("+" OR ".join(preference_conditions)+")")
        where=(" WHERE "+" AND ".join(conditions)) if conditions else ""
        with self.connect() as db:
            total=db.execute("SELECT COUNT(*) FROM jobs"+where,args).fetchone()[0]
            rows=db.execute("SELECT * FROM jobs"+where+" ORDER BY CAST(json_extract(match_json,'$.overall') AS INTEGER) DESC,posted_at DESC,fetched_at DESC LIMIT ? OFFSET ?",[*args,page_size,(page-1)*page_size]).fetchall()
        out=[]
        for row in rows:
            item=dict(row); item["match"]=json.loads(item.pop("match_json") or "{}")
            item["mobility_support"]=json.loads(item.pop("mobility", "[]") or "[]")
            item["description"]=item["description"][:1800]; out.append(item)
        return out,total

    def job(self, jid: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row=db.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
        if not row:
            return None
        item=dict(row); item["match"]=json.loads(item.pop("match_json") or "{}"); item["mobility_support"]=json.loads(item.pop("mobility", "[]") or "[]"); return item

    def update_match(self,jid:str,match:dict[str,Any])->None:
        with self.connect() as db:
            cur=db.execute("UPDATE jobs SET match_json=? WHERE id=?",(json.dumps(match,ensure_ascii=False),jid))
            if not cur.rowcount: raise ValueError("Unknown job id")

    def jobs_by_source(self,source:str)->list[dict[str,Any]]:
        with self.connect() as db:
            rows=db.execute("SELECT * FROM jobs WHERE source=?",(source,)).fetchall()
        out=[]
        for row in rows:
            item=dict(row); item["match"]=json.loads(item.pop("match_json") or "{}"); out.append(item)
        return out

    def source_is_due(self,source:str,ttl_seconds:int,retry_seconds:int=900,fingerprint:str="")->bool:
        now=time.time()
        with self.connect() as db:
            row=db.execute("SELECT last_attempt,last_success,fingerprint FROM source_sync WHERE source=?",(source,)).fetchone()
        if not row:return True
        if fingerprint and row["fingerprint"]!=fingerprint:return True
        if now-row["last_attempt"]<retry_seconds:return False
        return now-row["last_success"]>=ttl_seconds

    def mark_source_attempt(self,source:str,success:bool,fingerprint:str="")->None:
        now=time.time()
        with self.connect() as db:
            db.execute("INSERT INTO source_sync(source,last_attempt,last_success,fingerprint) VALUES(?,?,?,?) ON CONFLICT(source) DO UPDATE SET last_attempt=excluded.last_attempt,last_success=CASE WHEN ? THEN excluded.last_success ELSE source_sync.last_success END,fingerprint=excluded.fingerprint",
                       (source,now,now,fingerprint,int(success)))

    def set_status(self, jid: str, status: str) -> None:
        allowed={"New","Viewed","Saved","Ignored","Planning to Apply","Applied","Interview","Rejected","Offer","Closed"}
        if status not in allowed:
            raise ValueError("Unsupported status.")
        with self.connect() as db:
            row=db.execute("SELECT status FROM jobs WHERE id=?",(jid,)).fetchone()
            if not row:
                raise ValueError("Unknown job id.")
            old=row["status"]
            if old!=status:
                db.execute("UPDATE jobs SET status=? WHERE id=?",(status,jid))
                db.execute("INSERT INTO status_history(job_id,old_status,new_status) VALUES(?,?,?)",(jid,old,status))

    def status_history(self,jid:str,page:int=1,page_size:int=25)->tuple[list[dict[str,Any]],int]:
        page=max(1,page); page_size=max(1,min(100,page_size))
        with self.connect() as db:
            total=db.execute("SELECT COUNT(*) FROM status_history WHERE job_id=?",(jid,)).fetchone()[0]
            rows=db.execute("SELECT old_status,new_status,changed_at FROM status_history WHERE job_id=? ORDER BY id DESC LIMIT ? OFFSET ?",(jid,page_size,(page-1)*page_size))
            return [dict(x) for x in rows],total

    def save_document(self,did:str,jid:str,kind:str,content:str,eids:list[str],score:int,docx:str,pdf:str)->None:
        with self.connect() as db:
            db.execute("INSERT INTO documents(id,job_id,kind,content,evidence_ids,ats_score,path_docx,path_pdf) VALUES(?,?,?,?,?,?,?,?)",
                       (did,jid,kind,content,json.dumps(eids),score,docx,pdf))

    def documents(self,jid:str)->list[dict[str,Any]]:
        with self.connect() as db:
            rows=db.execute("SELECT * FROM documents WHERE job_id=? ORDER BY created_at DESC",(jid,))
        out=[]
        for row in rows:
            x=dict(row); x["evidence_ids"]=json.loads(x["evidence_ids"]); x.pop("content",None); out.append(x)
        return out
