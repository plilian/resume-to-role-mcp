from __future__ import annotations

import re
from typing import Any

from .preferences import infer_mobility_support

SKILLS={
"sql":"SQL","python":"Python","r programming":"R","excel":"Excel","power bi":"Power BI","tableau":"Tableau","looker":"Looker","metabase":"Metabase","bigquery":"BigQuery","snowflake":"Snowflake","dbt":"dbt","spark":"Apache Spark","pandas":"pandas","numpy":"NumPy","scikit-learn":"scikit-learn","machine learning":"Machine Learning","deep learning":"Deep Learning","statistics":"Statistics","a/b testing":"A/B Testing","experimentation":"Experimentation","funnel analysis":"Funnel Analysis","cohort analysis":"Cohort Analysis","retention":"Retention","churn":"Churn","segmentation":"Segmentation","forecasting":"Forecasting","data modeling":"Data Modeling","etl":"ETL","dashboard":"Dashboarding","analytics":"Analytics","product analytics":"Product Analytics","google analytics":"Google Analytics","amplitude":"Amplitude","mixpanel":"Mixpanel","jira":"Jira","roadmap":"Product Roadmap","product strategy":"Product Strategy","product discovery":"Product Discovery","product requirements":"Product Requirements","prd":"PRD","user stories":"User Stories","agile":"Agile","scrum":"Scrum","stakeholder management":"Stakeholder Management","market research":"Market Research","competitive analysis":"Competitive Analysis","business analysis":"Business Analysis","financial modeling":"Financial Modeling","monetization":"Monetization","go-to-market":"Go-to-Market","gtm":"Go-to-Market","growth":"Growth","cac":"CAC","ltv":"LTV","roas":"ROAS","attribution":"Attribution","crm":"CRM","marketing automation":"Marketing Automation","campaign analytics":"Campaign Analytics","generative ai":"Generative AI","llm":"LLM","large language model":"LLM","rag":"RAG","ai agents":"AI Agents","prompt engineering":"Prompt Engineering","automation":"Automation","natural language processing":"NLP","recommendation systems":"Recommendation Systems","game analytics":"Game Analytics","game economy":"Game Economy","blockchain":"Blockchain","web3":"Web3","on-chain analytics":"On-chain Analytics","communication":"Communication","leadership":"Leadership","product management":"Product Management","data visualization":"Data Visualization","data quality":"Data Quality","api":"API","api design":"API Design","b2b":"B2B","saas":"SaaS","fintech":"Fintech"}
SKILLS.update({
    "análisis de datos":"Data Analysis", "analisis de datos":"Data Analysis", "análisis de datos empresariales":"Data Analysis", "analista de datos":"Data Analysis", "analista de datos de videojuegos":"Game Analytics",
    "تحليل البيانات":"Data Analysis", "تحليلات البيانات":"Data Analysis", "محلل بيانات":"Data Analysis", "محللة بيانات":"Data Analysis", "تحلیل داده":"Data Analysis", "تحلیل داده‌ها":"Data Analysis", "تحلیلگر داده":"Data Analysis", "تحلیل‌گر داده":"Data Analysis",
    "análisis de negocio":"Business Analysis", "análisis empresarial":"Business Analysis", "تحليل الأعمال":"Business Analysis", "تحلیل کسب و کار":"Business Analysis",
    "gestión de producto":"Product Management", "gestión de productos":"Product Management", "إدارة المنتج":"Product Management", "إدارة المنتجات":"Product Management", "مدیریت محصول":"Product Management",
    "estrategia de producto":"Product Strategy", "استراتيجية المنتج":"Product Strategy", "استراتژی محصول":"Product Strategy",
    "gestión de proyectos":"Project Management", "إدارة المشاريع":"Project Management", "مدیریت پروژه":"Project Management",
    "aprendizaje automático":"Machine Learning", "تعلم الآلة":"Machine Learning", "التعلم الآلي":"Machine Learning", "یادگیری ماشین":"Machine Learning",
    "inteligencia artificial generativa":"Generative AI", "الذكاء الاصطناعي التوليدي":"Generative AI", "هوش مصنوعی مولد":"Generative AI",
    "visualización de datos":"Data Visualization", "تصور البيانات":"Data Visualization", "تصوير البيانات":"Data Visualization", "مصورسازی داده":"Data Visualization",
    "gestión de partes interesadas":"Stakeholder Management", "إدارة أصحاب المصلحة":"Stakeholder Management", "مدیریت ذی‌نفعان":"Stakeholder Management",
    "investigación de mercado":"Market Research", "أبحاث السوق":"Market Research", "تحقیقات بازار":"Market Research",
    "estadística":"Statistics", "estadísticas":"Statistics", "الإحصاء":"Statistics", "آمار":"Statistics",
    "tablero de control":"Dashboarding", "لوحة المعلومات":"Dashboarding", "داشبورد":"Dashboarding",
})
STOP=set("the and with for from that this you your are our will can have has was were not all into about who what when where how their they them then than job role team work working years year required requirements preferred responsibilities experience skills ability strong excellent including such across using build support lead manage develop drive ensure provide based new good plus other within while el la los las de del para con por una unos unas experiencia trabajo empresa datos producto equipo habilidades y que en es su sus como realizar esta este se los las más por para años responsable responsabilidades requisitos preferido requerida strong تێ we من و به از برای در با که این آن است است روی داده محصول تجربه مسئولیت مهارتها مهارت " .split())

def terms(text: str) -> list[str]:
    low=text.lower()
    return sorted({v for k,v in SKILLS.items() if re.search(r"(?<![a-z0-9])"+re.escape(k)+r"(?![a-z0-9])",low)})

def tokens(text: str) -> set[str]:
    normalized=text.lower()
    for alias,canonical in sorted(SKILLS.items(),key=lambda item:len(item[0]),reverse=True):
        if not alias.isascii():
            normalized=re.sub(r"(?<!\w)"+re.escape(alias)+r"(?!\w)",canonical.lower(),normalized,flags=re.UNICODE)
    values=re.findall(r"[^\W_][\w+#.-]{2,}",normalized,flags=re.UNICODE)
    return {x.strip(".-+#") for x in values if x.strip(".-+#") not in STOP}

def score_job(job: dict[str,Any], resumes: list[str], titles: list[str]) -> dict[str,Any]:
    jd=job.get("description",""); title=job.get("title",""); cv="\n".join(resumes).lower()
    jdskills=terms(title+"\n"+jd); candidate=terms(cv); matched=[x for x in jdskills if x in candidate]
    gaps=[x for x in jdskills if x not in candidate]; skill=round(100*len(matched)/len(jdskills)) if jdskills else None
    title_tokens=tokens(title)
    title_score=max([round(100*len(title_tokens&tokens(x))/max(1,len(tokens(x)))) for x in titles] or [0])
    jt=tokens(jd); overlap=round(100*len(jt&tokens(cv))/max(1,len(jt)))
    overall=skill if skill is not None else round(.7*overlap+.3*title_score)
    return {"overall":overall,"skills":skill,"matched_skills":matched,"job_skills":jdskills,
      "potential_gaps":gaps,"title_relevance":title_score,"description_overlap":overlap,
      "score_note":"JD skill coverage across every imported resume; title relevance is reported separately."}

def eligibility(job: dict[str,Any], countries: list[str]) -> str:
    explicit=str(job.get("eligibility","unknown")).lower()
    if explicit in {"eligible","likely eligible","ineligible","relocation available","sponsorship available"}: return explicit
    loc=str(job.get("location","")).lower()
    description=str(job.get("description","")).lower()
    mobility=infer_mobility_support(job)
    country_aliases={"united states":["united states","united states of america","usa","u.s.a.","us only","u.s. only","us","estados unidos","ee. uu.","الولايات المتحدة","أمريكا","ایالات متحده","آمریکا"],
      "canada":["canada","canadá","كندا","کانادا"],"united kingdom":["united kingdom","uk only","u.k.","reino unido","المملكة المتحدة","بريطانيا","بریتانیا"],"india":["india"],
      "australia":["australia"],"new zealand":["new zealand"],"singapore":["singapore"],
      "israel":["israel"],"switzerland":["switzerland"],"france":["france","francia","فرنسا","فرانسه"],"germany":["germany","alemania","ألمانيا","المانيا","آلمان"],
      "spain":["spain","españa","espana","إسبانيا","اسبانيا","اسپانیا"],"netherlands":["netherlands","the netherlands","países bajos","paises bajos","holanda","هولندا","هلند"],"finland":["finland","finlandia","فنلندا","فنلاند"],
      "denmark":["denmark","dinamarca","الدنمارك","دانمارک"],"turkey":["turkey","türkiye","turquía","turquia","تركيا","ترکیه"],"cyprus":["cyprus","chipre","قبرص","قبرس"],"portugal":["portugal","البرتغال","پرتغال"],
      "ireland":["ireland","irlanda","أيرلندا","ایرلند"],"sweden":["sweden"],"norway":["norway"],"poland":["poland"],
      "estonia":["estonia"],"austria":["austria"],"czech republic":["czech republic","czechia"]}
    selected_keys=set(); candidate_names=set()
    for country in countries:
        candidate=country.lower()
        matched_key=next((key for key,aliases in country_aliases.items() if candidate==key or candidate in aliases),None)
        if matched_key:
            selected_keys.add(matched_key); candidate_names.update([matched_key,*country_aliases[matched_key]])
        else:
            candidate_names.add(candidate)
    if any(re.search(r"(?<![a-z])"+re.escape(c)+r"(?![a-z])",loc) for c in candidate_names):
        if "visa_sponsorship" in mobility: return "sponsorship available"
        if "relocation" in mobility: return "relocation available"
        return "eligible"
    disallowed=[alias for key,aliases in country_aliases.items() if key not in selected_keys for alias in aliases]
    if any(re.search(r"(?<![a-z])"+re.escape(name)+r"(?![a-z])",loc) for name in disallowed): return "ineligible"
    if any(x in loc for x in ("worldwide","global","anywhere")) and countries: return "likely eligible"
    europe={"cyprus","turkey","türkiye","spain","netherlands","finland","denmark","germany","portugal","estonia","sweden","norway","ireland","austria","poland","czech republic","czechia","france","italy","belgium","greece","switzerland","united kingdom","uk"}
    if any(x in loc for x in ("emea","europe")) and any(c.lower() in europe for c in countries): return "likely eligible"
    if str(job.get("remote","unknown")).lower()=="remote" and countries and loc:
        generic={"remote","remote only","remote position","work from anywhere"}
        if loc.strip() not in generic and not any(x in loc for x in ("worldwide","global","emea","europe","anywhere")):
            return "ineligible"
    return "unknown"

def rank_evidence(text: str, query: str) -> int:
    q=terms(query)
    return len(set(terms(text))&set(q)) if q else len(tokens(text)&tokens(query))

def ats_estimate(content: str, job: dict[str,Any], kind: str) -> tuple[int,dict[str,Any]]:
    required=terms(job.get("title","")+"\n"+job.get("description","")); content_terms={x.lower() for x in terms(content)}; found=[x for x in required if x.lower() in content_terms]
    coverage=round(100*len(found)/len(required)) if required else 50
    heading_patterns={
      "summary":r"summary|profile|resumen|perfil|ملخص|الملخص|خلاصه|درباره من",
      "experience":r"experience|work history|experiencia|experiencia laboral|الخبرة|الخبرة العملية|سوابق العمل|تجربه کاری",
      "skills":r"skills|competencies|habilidades|competencias|المهارات|المهارات التقنية|مهارت‌ها|توانمندی‌ها",
      "education":r"education|formación|formacion|educación|educacion|التعليم|المؤهلات|تحصیلات|آموزش",
    }
    headings=[name for name,pattern in heading_patterns.items() if re.search(r"(?im)^\s*(?:"+pattern+r")\s*$",content)]
    fmt=100 if (kind=="resume" and len(headings)>=3) or kind=="cover_letter" else 60
    penalty=(12 if "|" in content or "\t" in content else 0)+(8 if len(content)>25000 else 0)
    score=max(0,min(100,round(.75*coverage+.25*fmt-penalty)))
    return score,{"job_keyword_coverage":coverage,"keywords_found":found,
      "keywords_missing":[x for x in required if x not in found],"format_score":fmt,"estimated_score_only":True}
