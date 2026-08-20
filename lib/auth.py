"""Simple admin authentication for protected sections."""

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
