import utils.preferences as prefs
from utils.onboarding import OnboardingChoice, OnboardingStep


def _isolate_prefs(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "PREFS_FILE", tmp_path / "preferences.json")
    monkeypatch.setattr(prefs, "ENV_FILE", tmp_path / ".env")


def test_onboarding_step_default_is_choose_goal(tmp_path, monkeypatch):
    _isolate_prefs(tmp_path, monkeypatch)
    assert prefs.get_onboarding_step() == OnboardingStep.CHOOSE_GOAL


def test_onboarding_step_defaults_to_done_when_seen(tmp_path, monkeypatch):
    _isolate_prefs(tmp_path, monkeypatch)
    prefs.save_preferences({"has_seen_onboarding": True})
    assert prefs.get_onboarding_step() == OnboardingStep.DONE


def test_set_onboarding_step_persists_and_marks_seen_on_done(tmp_path, monkeypatch):
    _isolate_prefs(tmp_path, monkeypatch)
    prefs.set_onboarding_step(OnboardingStep.PERMISSIONS)
    assert prefs.load_preferences()["onboarding_step"] == "permissions"
    assert prefs.load_preferences().get("has_seen_onboarding") in (None, False)

    prefs.set_onboarding_step(OnboardingStep.DONE)
    data = prefs.load_preferences()
    assert data["onboarding_step"] == "done"
    assert data["has_seen_onboarding"] is True


def test_onboarding_choice_roundtrip(tmp_path, monkeypatch):
    _isolate_prefs(tmp_path, monkeypatch)
    assert prefs.get_onboarding_choice() is None
    prefs.set_onboarding_choice(OnboardingChoice.FAST)
    assert prefs.get_onboarding_choice() == OnboardingChoice.FAST
    prefs.set_onboarding_choice(None)
    assert prefs.get_onboarding_choice() is None

