from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()


def create_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    anon_key = os.environ.get("SUPABASE_ANON_KEY")

    if not url or not anon_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY in environment.")

    return create_client(url, anon_key)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    return create_supabase_client()


def create_authenticated_supabase_client(access_token: str, refresh_token: str) -> Client:
    client = create_supabase_client()
    client.auth.set_session(access_token, refresh_token)
    return client
