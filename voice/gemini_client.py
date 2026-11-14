"""Gemini tool-calling client over Python's standard library HTTPS.

Converts `interfaces.TOOLS` into Gemini `functionDeclarations`, forces a tool call
(`mode="ANY"`), and returns `(tool_name, tool_args)` for `SpatialMemoryApp.call_tool`.

Rules enforced here:
- Keys come ONLY from `keys.get("gemini")` (`VEXO_GEMINI_API_KEY`) after `keys.prepare()`.
- Key is sent in the `x-goog-api-key` HTTP header, NEVER in a URL query string.
- HTTP redirects are blocked so the header is never forwarded elsewhere.
- Error messages include only HTTP status codes, never request headers, keys, or raw bodies.
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

import config
import keys
from interfaces import TOOLS

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_TIMEOUT = 30.0

# Verified Gemini 4 model IDs from the official hackathon builder guide.
# `config.GEMINI_MODEL` is set in `config.py` (gemini-4-hydrogen, per the builder guide).
GEMINI_4_MODELS = {
    "gemini-4-hydrogen": "Fast interactive workhorse recommended for tap-to-talk tool calling",
    "gemini-4-argon": "Balanced Gemini 4 model",
    "gemini-4-carbon": "Frontier reasoning Gemini 4 model",
}
RECOMMENDED_GEMINI_4_MODEL = "gemini-4-hydrogen"

# Gemini 4 prohibits custom sampling controls and legacy thinking budgets.
FORBIDDEN_GENERATION_KEYS = (
    "temperature",
    "topP",
    "top_p",
    "topK",
    "top_k",
    "thinkingBudget",
    "thinking_budget",
)
VALID_THINKING_LEVELS = ("low", "medium", "high")


class GeminiError(Exception):
    """Raised when Gemini configuration, transport, or tool selection fails safely."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse all HTTP redirects so `x-goog-api-key` never leaves the Gemini endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return context


def build_function_declarations(tools: Optional[List[dict]] = None) -> List[dict]:
    """Convert `interfaces.TOOLS` entries into Gemini `functionDeclarations`."""
    specs = TOOLS if tools is None else tools
    declarations: List[dict] = []
    for tool in specs:
        decl: Dict[str, object] = {
            "name": tool["name"],
            "description": tool.get("description", ""),
        }
        params = tool.get("parameters") or {}
        if params:
            properties: Dict[str, dict] = {}
            required: List[str] = []
            for param_name, param_spec in params.items():
                prop: Dict[str, object] = {"type": param_spec.get("type", "string")}
                if "description" in param_spec:
                    prop["description"] = param_spec["description"]
                if "enum" in param_spec:
                    prop["enum"] = list(param_spec["enum"])
                properties[param_name] = prop
                if param_spec.get("required"):
                    required.append(param_name)
            schema: Dict[str, object] = {
                "type": "object",
                "properties": properties,
            }
            if required:
                schema["required"] = required
            decl["parameters"] = schema
        declarations.append(decl)
    return declarations


def build_system_instruction(landmark_summary: str, route_active: bool = False) -> str:
    """Concise system prompt grounding Gemini on saved landmark IDs without geometry."""
    summary = (landmark_summary or "").strip() or "none"
    active_label = "yes" if route_active else "no"
    return (
        "You are the voice intent router for a wearable indoor spatial-memory band.\n"
        "Pick exactly one tool call that matches what the wearer said.\n"
        "Rules:\n"
        "- Never invent coordinates, step counts, distances, or turn directions; code computes all geometry.\n"
        "- Saved landmarks (id=label): %s\n"
        "- Route currently active: %s\n"
        "- When referring to an existing saved landmark in `navigate_to`, `save_note`, or `reanchor`, "
        "use its exact id from the saved landmarks list (for example `lm1`).\n"
        "- If the wearer asks to go back to the start or beginning (and no saved landmark specifically "
        "matches better), call `navigate_to` with `target` set to `\"start\"`.\n"
        "- The text comes from speech recognition on a small wrist microphone, so words are often "
        "misheard. Read it as the closest sensible command for this app before giving up. For example: "
        "'same dislocation' or 'save this vacation' means 'save this location'; 'stat route' or "
        "'start root' means 'start route'; 'take me back' with no place means the start; "
        "'remember this' or 'mark this' means save a landmark.\n"
        "- To save a place: call `remember_landmark`. If no name was said, use the label `\"spot N\"` "
        "where N is one more than the number of saved landmarks, rather than asking.\n"
        "- If no route is active and the wearer wants to save a place or walk, call `start_route` first "
        "only when they clearly asked to start; otherwise still pick the closest tool.\n"
        "- Only if two saved landmarks match equally, or the text has no plausible command at all, "
        "call `ask_user` with a short question that offers the two or three likeliest commands."
    ) % (summary, active_label)


def build_request_payload(
    text: str,
    landmark_summary: str,
    route_active: bool = False,
    tools: Optional[List[dict]] = None,
    thinking_level: Optional[str] = None,
) -> dict:
    """Construct the JSON body for Gemini 4 `generateContent`.

    Never sends `temperature`, `topP`/`top_p`, `topK`/`top_k`, or `thinkingBudget`:
    Gemini 4 models prohibit custom sampling parameters and legacy thinking budgets,
    and `gemini-4-hydrogen` rejects `'minimal'` thinking level. Omits `generationConfig`
    by default so Gemini 4 defaults apply cleanly.
    """
    payload: Dict[str, object] = {
        "systemInstruction": {
            "parts": [{"text": build_system_instruction(landmark_summary, route_active=route_active)}],
        },
        "contents": [
            {"role": "user", "parts": [{"text": text.strip()}]},
        ],
        "tools": [
            {"functionDeclarations": build_function_declarations(tools)},
        ],
        "toolConfig": {
            "functionCallingConfig": {"mode": "ANY"},
        },
    }
    if thinking_level is not None:
        level = str(thinking_level).strip().lower()
        if level not in VALID_THINKING_LEVELS:
            raise GeminiError(
                "Invalid Gemini 4 thinking_level %r; allowed values are %s."
                % (thinking_level, ", ".join(VALID_THINKING_LEVELS))
            )
        payload["generationConfig"] = {
            "thinkingConfig": {"thinkingLevel": level},
        }
    return payload


def _resolve_model(model: Optional[str]) -> str:
    chosen = model if model is not None else config.GEMINI_MODEL
    if not chosen or not str(chosen).strip():
        raise GeminiError(
            "GEMINI_MODEL is not set in config.py (recommended Gemini 4 model: '%s')."
            % RECOMMENDED_GEMINI_4_MODEL
        )
    cleaned = str(chosen).strip()
    if cleaned.startswith("models/"):
        cleaned = cleaned[len("models/"):]
    if not cleaned:
        raise GeminiError("GEMINI_MODEL is empty.")
    return cleaned


def _resolve_key(api_key: Optional[str]) -> str:
    keys.prepare()
    if api_key is not None and api_key.strip():
        secret = api_key.strip()
    else:
        try:
            secret = keys.get("gemini", required=True)
        except SystemExit as exc:
            raise GeminiError("Missing VEXO_GEMINI_API_KEY.") from exc
    if not secret.isascii() or not secret.isprintable() or " " in secret:
        raise GeminiError("VEXO_GEMINI_API_KEY contains whitespace or non-printable characters.")
    return secret


def choose_tool(
    text: str,
    landmark_summary: str,
    route_active: bool = False,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    tools: Optional[List[dict]] = None,
    opener=None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[str, dict]:
    """Ask Gemini to pick one tool from `tools` (`interfaces.TOOLS` by default).

    Returns `(tool_name, tool_args)`. Raises `GeminiError` on any config, network,
    HTTP, or validation failure without ever exposing the API key.
    """
    if not text or not str(text).strip():
        raise GeminiError("Cannot choose a tool for empty text.")

    resolved_model = _resolve_model(model)
    secret = _resolve_key(api_key)
    tool_specs = list(TOOLS if tools is None else tools)
    allowed_names = {t["name"] for t in tool_specs}

    quoted_model = urllib.parse.quote(resolved_model, safe="-._")
    url = "%s/%s:generateContent" % (API_BASE, quoted_model)
    payload = build_request_payload(
        text=str(text),
        landmark_summary=landmark_summary,
        route_active=route_active,
        tools=tool_specs,
    )

    if opener is None:
        opener = urllib.request.build_opener(
            _NoRedirect,
            urllib.request.HTTPSHandler(context=_ssl_context()),
        )

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": secret,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read(4000000).decode("utf-8")
            answer = json.loads(raw)
    except urllib.error.HTTPError as err:
        raise GeminiError("Gemini request failed (HTTP status %d)." % err.code) from None
    except ssl.SSLCertVerificationError:
        raise GeminiError(
            "SSL certificate check failed for generativelanguage.googleapis.com."
        ) from None
    except (OSError, ValueError):
        raise GeminiError("Could not reach Gemini API or decode response.") from None

    return _parse_function_call(answer, allowed_names)


def _parse_function_call(answer: object, allowed_names: set) -> Tuple[str, dict]:
    if not isinstance(answer, dict):
        raise GeminiError("Gemini response is not a JSON object.")
    candidates = answer.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiError("Gemini response contained no candidates.")
    first = candidates[0]
    if not isinstance(first, dict):
        raise GeminiError("Gemini candidate is malformed.")
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise GeminiError("Gemini candidate contained no content parts.")

    fn_call = None
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("functionCall"), dict):
            fn_call = part["functionCall"]
            break
    if fn_call is None:
        raise GeminiError("Gemini did not return a functionCall.")

    name = fn_call.get("name")
    if not isinstance(name, str) or name not in allowed_names:
        raise GeminiError("Gemini returned an unknown tool name.")

    raw_args = fn_call.get("args")
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, dict):
        raise GeminiError("Gemini functionCall args must be an object.")

    clean_args = {k: v for k, v in raw_args.items() if v is not None}
    return name, clean_args
