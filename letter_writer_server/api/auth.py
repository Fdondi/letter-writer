import hmac
import os

from fastapi import APIRouter, Request, Response, Depends, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from authlib.integrations.starlette_client import OAuth, OAuthError
from letter_writer_server.core.config import settings
from letter_writer_server.core.session import Session, get_session

router = APIRouter()

oauth = OAuth()
oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
        'prompt': 'select_account',
    }
)

@router.get("/login/")
async def login(request: Request):
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/callback/")
async def auth_callback(request: Request, session: Session = Depends(get_session)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as error:
        raise HTTPException(status_code=400, detail=error.error)
        
    user_info = token.get('userinfo')
    if not user_info:
        user_info = await oauth.google.userinfo(token=token)

    if user_info:
        session['user'] = {
            'id': user_info.get('sub'), 
            'email': user_info.get('email'),
            'name': user_info.get('name'),
            'picture': user_info.get('picture'),
            'provider': 'google'
        }
    
    return RedirectResponse(url="/")

@router.get("/login/callback/") # Alias for compatibility
async def auth_callback_alias(request: Request, session: Session = Depends(get_session)):
    return await auth_callback(request, session)

@router.post("/logout/")
async def logout(request: Request, response: Response, session: Session = Depends(get_session)):
    session.clear()
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "ok", "message": "Logged out successfully"}

@router.get("/user/")
async def get_current_user(session: Session = Depends(get_session)):
    user = session.get('user')
    return {
        "authenticated": bool(user),
        "user": user
    }

@router.get("/status/")
async def auth_status(session: Session = Depends(get_session)):
    user = session.get('user')
    return {
        "authenticated": bool(user),
        "user": user,
        "auth_available": True,
        "cors_available": True
    }

@router.get("/csrf-token/")
async def csrf_token():
    return {"csrfToken": "not-needed-for-cookie-session"}


class TestLoginRequest(BaseModel):
    password: str


@router.post("/test-login/")
async def test_login(body: TestLoginRequest, request: Request, response: Response, session: Session = Depends(get_session)):
    """Authenticate with a shared test password (set TEST_AUTH_PASSWORD in .env).
    Disabled when the env var is unset, so production is never affected."""
    expected = settings.TEST_AUTH_PASSWORD
    if not expected:
        raise HTTPException(status_code=404, detail="Test login is not enabled")
    if not hmac.compare_digest(body.password, expected):
        raise HTTPException(status_code=401, detail="Invalid password")

    session['user'] = {
        'id': 'test-user',
        'email': 'test@letterwriter.dev',
        'name': 'Test User',
        'picture': None,
        'provider': 'test',
    }
    return {"status": "ok", "user": session['user']}
