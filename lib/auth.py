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


# --- OT PIC unit gate (ot_pic_app.py only) ---------------------------------

_PIC_UNIT_KEY = "ot_pic_unit"
_PIC_SCOPE_KEY = "ot_pic_scope"  # "unit" | "all"
_PIC_ALL_LABEL = "All Jabatan/Unit"


def _normalize_unit_key(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _pic_unit_password_map() -> dict[str, str]:
    """
    Secrets table [ot_pic_unit_passwords]:
      "Jabatan/Unit name" = "password"

    Keys are matched case-insensitively to sheet Jabatan/Unit values.
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
    """Master password to view all PIC units (ot_pic_all_password or admin_password)."""
    try:
        pw = str(st.secrets.get("ot_pic_all_password", "") or "")
        if pw:
            return pw
        return str(st.secrets.get("admin_password", "") or "")
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


def pic_is_admin_all() -> bool:
    """True when logged in with All Jabatan/Unit admin password."""
    return st.session_state.get(_PIC_SCOPE_KEY) == "all"


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

    # Only show units that have a password configured (matched to sheet names)
    configured_units = []
    for unit in unit_options:
        if _normalize_unit_key(unit) in passwords:
            configured_units.append(unit)

    # Always show All first; admin password checked on submit.
    login_options: list[str] = [_PIC_ALL_LABEL, *configured_units]
    if not configured_units:
        st.warning(
            "No Jabatan/Unit passwords match the sheet. "
            "Check secret keys against Jabatan/Unit names."
        )
    if not all_pw:
        st.caption(
            "To use **All Jabatan/Unit**, add `ot_pic_all_password` or "
            "`admin_password` in this app's Streamlit secrets."
        )

    st.subheader("Sign in")
    with st.form("ot_pic_unit_login"):
        selected = st.selectbox(
            "Jabatan/Unit",
            options=login_options or ["—"],
            key="ot_pic_login_unit",
        )
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

        if submitted:
            if not selected or selected == "—":
                st.error("Select a Jabatan/Unit")
            elif selected == _PIC_ALL_LABEL:
                if not all_pw:
                    st.error(
                        "All-access password is not configured. "
                        "Add ot_pic_all_password or admin_password in secrets."
                    )
                elif password == all_pw:
                    st.session_state[_PIC_SCOPE_KEY] = "all"
                    st.session_state.pop(_PIC_UNIT_KEY, None)
                    st.rerun()
                else:
                    st.error("Incorrect password")
            else:
                expected = passwords.get(_normalize_unit_key(selected), "")
                if expected and password == expected:
                    st.session_state[_PIC_SCOPE_KEY] = "unit"
                    st.session_state[_PIC_UNIT_KEY] = selected
                    st.rerun()
                else:
                    st.error("Incorrect password")
    return False
