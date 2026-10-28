import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_skill_and_template_expose_four_languages_and_optional_filters():
    skill=(ROOT/"skills"/"career-compass"/"SKILL.md").read_text(encoding="utf-8-sig")
    template=json.loads((ROOT/"profile.template.json").read_text(encoding="utf-8-sig"))
    assert skill.startswith("---\nname: career-compass\n")
    for code in ("en","fa","es","ar"):
        assert code in skill
    for option in ("work_arrangements","mobility_support","remote","hybrid","in_person","relocation","visa_sponsorship"):
        assert option in skill
    assert template["preferred_language"]=="en"
    assert template["document_language"]=="job"
    assert template["work_arrangements"]==[]
    assert template["mobility_support"]==[]


def test_skill_uses_signed_in_host_and_requires_selected_job_documents():
    skill=(ROOT/"skills"/"career-compass"/"SKILL.md").read_text(encoding="utf-8-sig")
    assert "signed-in model" in skill
    assert "Wait for the user's selection" in skill
    assert "source_search_queries(localized_titles" in skill
    assert "right-to-left" in skill
