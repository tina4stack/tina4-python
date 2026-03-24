"""Tests for the form_token template function."""
import os
import json
import base64
import pytest

from tina4_python.frond import Frond


def _decode_jwt_payload(token: str) -> dict:
    """Decode the payload from a JWT without validation."""
    parts = token.split(".")
    assert len(parts) == 3, f"Expected 3 dot-separated parts, got {len(parts)}"
    # Verify each part is base64url
    for part in parts:
        assert len(part) > 0, "Empty JWT segment"

    payload_b64 = parts[1]
    # Add padding
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(payload_bytes)


def _extract_token_from_html(html_output: str) -> str:
    """Extract the JWT value from the rendered hidden input element."""
    assert '<input type="hidden" name="formToken" value="' in html_output, (
        f"Expected hidden input element, got: {html_output!r}"
    )
    start = html_output.index('value="') + len('value="')
    end = html_output.index('"', start)
    return html_output[start:end]


@pytest.fixture
def engine(tmp_path):
    os.environ["SECRET"] = "test-secret-key"
    e = Frond(template_dir=str(tmp_path))
    yield e
    os.environ.pop("SECRET", None)


class TestFormTokenGlobal:
    """Test {{ form_token() }} as a global function."""

    def test_renders_hidden_input(self, engine):
        output = engine.render_string("{{ form_token() }}")
        assert '<input type="hidden" name="formToken" value="' in output
        assert output.strip().endswith('">')

    def test_not_html_escaped(self, engine):
        output = engine.render_string("{{ form_token() }}")
        # Must NOT contain escaped angle brackets
        assert "&lt;" not in output
        assert "&gt;" not in output

    def test_token_is_valid_jwt(self, engine):
        output = engine.render_string("{{ form_token() }}")
        token = _extract_token_from_html(output)
        parts = token.split(".")
        assert len(parts) == 3, "Token must have 3 dot-separated base64 parts"
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "form"

    def test_basic_payload(self, engine):
        output = engine.render_string("{{ form_token() }}")
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "form"
        assert "context" not in payload
        assert "ref" not in payload

    def test_context_only(self, engine):
        output = engine.render_string('{{ form_token("my_context") }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "form"
        assert payload["context"] == "my_context"
        assert "ref" not in payload

    def test_context_and_ref(self, engine):
        output = engine.render_string('{{ form_token("checkout|order_123") }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "form"
        assert payload["context"] == "checkout"
        assert payload["ref"] == "order_123"


class TestFormTokenFilter:
    """Test {{ value | form_token }} as a filter."""

    def test_filter_renders_hidden_input(self, engine):
        output = engine.render_string('{{ "admin" | form_token }}')
        assert '<input type="hidden" name="formToken" value="' in output

    def test_filter_with_context(self, engine):
        output = engine.render_string('{{ "admin" | form_token }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["context"] == "admin"

    def test_filter_with_pipe_descriptor(self, engine):
        output = engine.render_string('{{ "checkout|order_123" | form_token }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["context"] == "checkout"
        assert payload["ref"] == "order_123"


class TestFormTokenJWTStructure:
    """Test the JWT structure and claims of generated tokens."""

    def test_token_has_iat_claim(self, engine):
        output = engine.render_string("{{ form_token() }}")
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert "iat" in payload
        assert isinstance(payload["iat"], int)

    def test_token_has_exp_claim(self, engine):
        output = engine.render_string("{{ form_token() }}")
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_each_render_produces_unique_token(self, engine):
        import time
        output1 = engine.render_string("{{ form_token() }}")
        time.sleep(1.1)
        output2 = engine.render_string("{{ form_token() }}")
        token1 = _extract_token_from_html(output1)
        token2 = _extract_token_from_html(output2)
        assert token1 != token2

    def test_token_signature_validates(self, engine):
        from tina4_python.auth import Auth
        output = engine.render_string("{{ form_token() }}")
        token = _extract_token_from_html(output)
        auth = Auth(secret="test-secret-key")
        payload = auth.valid_token(token)
        assert payload is not None
        assert payload["type"] == "form"


class TestFormTokenDescriptorEdgeCases:
    """Test edge cases in descriptor parsing."""

    def test_empty_string_descriptor(self, engine):
        output = engine.render_string('{{ form_token("") }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "form"
        assert "context" not in payload

    def test_descriptor_with_special_chars(self, engine):
        output = engine.render_string('{{ form_token("user-profile_v2") }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["context"] == "user-profile_v2"

    def test_descriptor_with_multiple_pipes(self, engine):
        output = engine.render_string('{{ form_token("checkout|order_123|extra") }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["context"] == "checkout"
        # split("|", 1) means ref gets the rest
        assert payload["ref"] == "order_123|extra"

    def test_filter_empty_string(self, engine):
        output = engine.render_string('{{ "" | form_token }}')
        token = _extract_token_from_html(output)
        payload = _decode_jwt_payload(token)
        assert payload["type"] == "form"

    def test_hidden_input_name_attribute(self, engine):
        output = engine.render_string("{{ form_token() }}")
        assert 'name="formToken"' in output

    def test_hidden_input_type_attribute(self, engine):
        output = engine.render_string("{{ form_token() }}")
        assert 'type="hidden"' in output

    def test_form_token_in_template_with_other_content(self, engine):
        output = engine.render_string('<form>{{ form_token() }}<button>Submit</button></form>')
        assert "<form>" in output
        assert '<input type="hidden" name="formToken"' in output
        assert "<button>Submit</button>" in output
        assert "</form>" in output

    def test_form_token_uses_secret_env(self, engine):
        """Token should be signed with the SECRET env var."""
        from tina4_python.auth import Auth
        output = engine.render_string("{{ form_token() }}")
        token = _extract_token_from_html(output)
        # Should validate with the same secret
        auth = Auth(secret="test-secret-key")
        assert auth.valid_token(token) is not None
        # Should NOT validate with a different secret
        wrong_auth = Auth(secret="wrong-secret")
        assert wrong_auth.valid_token(token) is None
