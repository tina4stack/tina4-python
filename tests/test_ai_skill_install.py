"""`tina4 ai` must install the actual SKILL files (project + global), not just a
CLAUDE.md pointer. Real network fetch from the release tag, no mocks."""
import os

from tina4_python.ai import install_skills, _skill_block, _DEV_SKILL


def test_install_skills_lands_in_project_and_global(tmp_path):
    # Pin to a tag known to carry the split skills so the test is deterministic.
    os.environ["TINA4_SKILLS_REF"] = "3.13.59"
    proj_skills = tmp_path / "proj" / ".claude" / "skills"
    global_skills = tmp_path / "home" / ".claude" / "skills"

    installed = install_skills(root=str(tmp_path / "proj"),
                               targets=[proj_skills, global_skills])

    assert set(installed) == {_DEV_SKILL, "tina4-js", "tina4-maintainer"}
    for dest in (proj_skills, global_skills):
        for skill in (_DEV_SKILL, "tina4-js", "tina4-maintainer"):
            assert (dest / skill / "SKILL.md").exists(), f"{skill}/SKILL.md missing in {dest}"
        # a reference file came down too
        assert (dest / _DEV_SKILL / "references" / "data-and-orm.md").exists()

    body = (proj_skills / _DEV_SKILL / "SKILL.md").read_text()
    assert "The Tina4 Working Method" in body  # the real 3.13.59 content


def test_claude_skill_block_uses_split_skill_name():
    block = _skill_block("CLAUDE.md")
    assert _DEV_SKILL in block                             # tina4-developer-python
    assert "skills/tina4-developer/SKILL.md" not in block  # old pre-split name gone
