"""
app/persona.py -- HookReel agent persona manager.

Loads and saves the agent identity from app/persona.json.
Provides name, greeting, and personality style for use by the agent.
"""

import json
import os
import re

from app.logger import get_logger

logger = get_logger(__name__)

_PERSONA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "persona.json")

_DEFAULT_PERSONA = {
    "name": "MrSmee",
    "version": "1.0",
    "version_name": "Hook",
    "personality": "pirate",
    "greeting": "Ahoy! MrSmee at your service, Captain. What can I find for ye today?",
    "custom_greeting": None,
}

_VALID_PERSONALITIES = {"pirate", "professional", "friendly"}


def load_persona() -> dict:
    """
    Read app/persona.json and return the persona dict.
    Returns the default persona if the file is missing or corrupt.
    """
    try:
        with open(_PERSONA_PATH, "r") as fh:
            data = json.load(fh)
        # Fill in any missing keys from defaults
        for key, value in _DEFAULT_PERSONA.items():
            if key not in data:
                data[key] = value
        return data
    except FileNotFoundError:
        logger.warning("[HookReel] persona.json not found -- using defaults")
        return dict(_DEFAULT_PERSONA)
    except Exception as exc:
        logger.error("[HookReel] load_persona error: %s", exc)
        return dict(_DEFAULT_PERSONA)


def save_persona(persona: dict) -> bool:
    """
    Write the persona dict to app/persona.json.
    Returns True if saved successfully, False on error.
    """
    try:
        with open(_PERSONA_PATH, "w") as fh:
            json.dump(persona, fh, indent=4)
        logger.info("[HookReel] persona.json saved")
        return True
    except Exception as exc:
        logger.error("[HookReel] save_persona error: %s", exc)
        return False


def get_name() -> str:
    """Return the current agent name. Default: MrSmee."""
    return load_persona().get("name", "MrSmee")


def get_personality() -> str:
    """Return the current personality style. Default: pirate."""
    return load_persona().get("personality", "pirate")


def get_greeting() -> str:
    """
    Return the greeting string with the agent name substituted in.
    Returns custom_greeting if set, otherwise the standard greeting.
    """
    persona = load_persona()
    custom = persona.get("custom_greeting")
    if custom:
        return custom.replace("{name}", persona["name"])
    greeting = persona.get("greeting", _DEFAULT_PERSONA["greeting"])
    return greeting.replace("MrSmee", persona["name"])


def update_name(new_name: str) -> bool:
    """
    Update the agent name in persona.json.
    Validates: letters, spaces, hyphens only, max 30 characters.
    Returns True if updated, False if invalid or save failed.
    """
    new_name = new_name.strip()
    if not new_name:
        logger.warning("[HookReel] update_name: empty name rejected")
        return False
    if len(new_name) > 30:
        logger.warning("[HookReel] update_name: name too long (%d chars)", len(new_name))
        return False
    if not re.match(r"^[A-Za-z][A-Za-z0-9 \-]*$", new_name):
        logger.warning("[HookReel] update_name: invalid characters in '%s'", new_name)
        return False
    persona = load_persona()
    persona["name"] = new_name
    return save_persona(persona)


def update_personality(style: str) -> bool:
    """
    Update the personality style in persona.json.
    Valid styles: pirate, professional, friendly.
    Returns True if updated, False if invalid style.
    """
    style = style.strip().lower()
    if style not in _VALID_PERSONALITIES:
        logger.warning(
            "[HookReel] update_personality: invalid style '%s'", style
        )
        return False
    persona = load_persona()
    persona["personality"] = style
    return save_persona(persona)


def get_system_prompt_personality(personality: str) -> str:
    """
    Return the personality instruction block for the system prompt.
    """
    if personality == "pirate":
        return (
            "You have a pirate personality. Use nautical references naturally. "
            "Address the user as Captain. Occasionally use Ahoy and Aye. "
            "Keep it fun but never let it get in the way of being helpful."
        )
    elif personality == "professional":
        return (
            "You have a professional personality. Be formal, precise, and efficient. "
            "No pirate references or casual language."
        )
    elif personality == "friendly":
        return (
            "You have a friendly, warm personality. Be casual and encouraging. "
            "No pirate references."
        )
    return ""
