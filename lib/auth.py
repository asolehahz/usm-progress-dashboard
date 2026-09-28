"""Simple authentication for protected sections."""

from __future__ import annotations

import streamlit as st


def is_admin() -> bool:
    return st.session_state.get("is_admin", False)


def admin_login_form() -> bool:
    """Show login form; returns True if already authenticated."""
    if is_admin():
        st.success("Logged in as admin")
        if st.button("Log out", key="admin_logout"):
            st.session_state["is_admin"] = False
            st.rerun()
        return True

    with st.form("admin_login"):
        password = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button("Log in")
        if submitted:
            expected = st.secrets.get("admin_password", "")
            if expected and password == expected:
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("Incorrect password")
    return False


# --- OT Staff page gate (app.py Overview → OT Staff) -----------------------

_OT_STAFF_KEY = "ot_staff_unlocked"


def is_ot_staff_unlocked() -> bool:
    return bool(st.session_state.get(_OT_STAFF_KEY, False))


def ot_staff_login_form() -> bool:
    """
    Password gate for the OT Staff page in the main progress app.

    Uses secret `ot_staff_password` (separate from admin_password).
    Returns True when authenticated.
    """
    if is_ot_staff_unlocked():
        st.success("OT Staff unlocked")
        if st.button("Lock OT Staff", key="ot_staff_logout"):
            st.session_state[_OT_STAFF_KEY] = False
            st.rerun()
        return True

    expected = ""
    try:
        expected = str(st.secrets.get("ot_staff_password", "") or "")
    except Exception:
        expected = ""

    if not expected:
        st.error(
            "OT Staff password is not configured. "
            "Add `ot_staff_password` in Streamlit secrets."
        )
        return False

    st.subheader("OT Staff — sign in")
    with st.form("ot_staff_login"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Unlock")
        if submitted:
            if password == expected:
                st.session_state[_OT_STAFF_KEY] = True
                st.rerun()
            st.error("Incorrect password")
    return False


# --- OT PIC unit gate (ot_pic_app.py only) ---------------------------------

_PIC_UNIT_KEY = "ot_pic_unit"
_PIC_SCOPE_KEY = "ot_pic_scope"  # "unit" | "all"


def _normalize_unit_key(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _unit_key_variants(name: str) -> set[str]:
    """
    Match sheet Jabatan/Unit to secret keys even if Desasiswa/DS prefix differs.

    e.g. 'Desasiswa Bakti Permai' ↔ 'Bakti Permai' ↔ 'DS Bakti Permai'
    """
    norm = _normalize_unit_key(name)
    if not norm:
        return set()
    keys = {norm}
    stripped = norm
    for prefix in ("desasiswa ", "desasisiwa ", "ds ", "desa "):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].strip()
            if stripped:
                keys.add(stripped)
    # Also allow with canonical Desasiswa prefix
    if stripped and not stripped.startswith("desasiswa"):
        keys.add(f"desasiswa {stripped}")
        keys.add(f"ds {stripped}")
    return {k for k in keys if k}


def _password_for_unit(unit: str, passwords: dict[str, str]) -> str:
    """Return password for a sheet unit, or '' if no secret key matches."""
    unit_keys = _unit_key_variants(unit)
    for key, pw in passwords.items():
        if key in unit_keys or (_unit_key_variants(key) & unit_keys):
            return pw
    return ""


def _pic_unit_password_map() -> dict[str, str]:
    """
    Secrets table [ot_pic_unit_passwords]:
      "Jabatan/Unit name" = "password"

    Keys are matched case-insensitively to sheet Jabatan/Unit values
    (Desasiswa / DS prefix optional).
    """
    try:
        raw = st.secrets.get("ot_pic_unit_passwords", {})
    except Exception:
        return {}
    if not raw:
        return {}
    out: dict[str, str] = {}
    for key, value in dict(raw).items():
        norm = _normalize_unit_key(str(key))
        if norm:
            out[norm] = str(value)
    return out


def _pic_all_password() -> str:
    """Optional master password that can view all PIC units."""
    try:
        return str(st.secrets.get("ot_pic_all_password", "") or "")
    except Exception:
        return ""


def pic_auth_unit() -> str | None:
    """Logged-in Jabatan/Unit name, or None if full access / not logged in."""
    if st.session_state.get(_PIC_SCOPE_KEY) == "all":
        return None
    unit = st.session_state.get(_PIC_UNIT_KEY)
    return str(unit) if unit else None


def pic_is_authenticated() -> bool:
    scope = st.session_state.get(_PIC_SCOPE_KEY)
    if scope == "all":
        return True
    return bool(st.session_state.get(_PIC_UNIT_KEY))


def pic_logout():
    st.session_state.pop(_PIC_UNIT_KEY, None)
    st.session_state.pop(_PIC_SCOPE_KEY, None)


def pic_unit_login_form(unit_options: list[str]) -> bool:
    """
    Gate for ot_pic_app: pick Jabatan/Unit + password, or master password for all.

    Returns True when authenticated.
    """
    if pic_is_authenticated():
        scope = st.session_state.get(_PIC_SCOPE_KEY)
        if scope == "all":
            st.success("Logged in — all Jabatan/Unit")
        else:
            st.success(f"Logged in — {st.session_state.get(_PIC_UNIT_KEY)}")
        if st.button("Log out", key="ot_pic_logout"):
            pic_logout()
            st.rerun()
        return True

    passwords = _pic_unit_password_map()
    all_pw = _pic_all_password()
    if not passwords and not all_pw:
        st.error(
            "PIC access is not configured. Add `[ot_pic_unit_passwords]` "
            "(and optional `ot_pic_all_password`) in Streamlit secrets."
        )
        return False

    # Sheet units that have a matching password secret (prefix-tolerant).
    configured_units = [
        unit for unit in unit_options if _password_for_unit(unit, passwords)
    ]

    # Secret keys that do not match any sheet Jabatan/Unit (helps fix typos).
    sheet_key_set: set[str] = set()
    for unit in unit_options:
        sheet_key_set |= _unit_key_variants(unit)
    unmatched_secrets = sorted(
        key
        for key in passwords
        if not (_unit_key_variants(key) & sheet_key_set)
    )

    st.subheader("Sign in")
    if unmatched_secrets:
        st.caption(
            "These secret unit names do not match the OT PIC sheet "
            f"(fix spelling): {', '.join(unmatched_secrets)}"
        )
    with st.form("ot_pic_unit_login"):
        mode = st.radio(
            "Access",
            options=["My Jabatan/Unit", "All units (admin)"]
            if all_pw
            else ["My Jabatan/Unit"],
            horizontal=True,
            key="ot_pic_login_mode",
        )
        selected_unit = None
        if mode == "My Jabatan/Unit":
            if not configured_units:
                st.warning(
                    "No Jabatan/Unit passwords match the sheet. "
                    "In Streamlit secrets, add a key that matches the sheet "
                    "Jabatan/Unit name (e.g. `Desasiswa Bakti Permai`). "
                    f"Sheet units: {', '.join(unit_options) if unit_options else '(none)'}."
                )
            selected_unit = st.selectbox(
                "Jabatan/Unit",
                options=configured_units or ["—"],
                key="ot_pic_login_unit",
            )
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

        if submitted:
            if mode.startswith("All") and all_pw:
                if password == all_pw:
                    st.session_state[_PIC_SCOPE_KEY] = "all"
                    st.session_state.pop(_PIC_UNIT_KEY, None)
                    st.rerun()
                st.error("Incorrect password")
            else:
                if not selected_unit or selected_unit == "—":
                    st.error("Select a Jabatan/Unit")
                else:
                    expected = _password_for_unit(selected_unit, passwords)
                    if expected and password == expected:
                        st.session_state[_PIC_SCOPE_KEY] = "unit"
                        st.session_state[_PIC_UNIT_KEY] = selected_unit
                        st.rerun()
                    st.error("Incorrect password")
    return False
