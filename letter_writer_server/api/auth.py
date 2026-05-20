import time
import httpx
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from letter_writer_server.core.rate_limit import limiter
from authlib.integrations.starlette_client import OAuth, OAuthError
from letter_writer_server.core.config import settings
from letter_writer_server.core.session import Session, get_session

router = APIRouter()

def _oauth_is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)

# Explicit Google OIDC endpoints (no discovery fetch on /login/). Authlib stores
# issuer/jwks_uri/userinfo_endpoint as top-level register() kwargs → server_metadata.
oauth = OAuth()
oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    authorize_url='https://accounts.google.com/o/oauth2/v2/auth',
    access_token_url='https://oauth2.googleapis.com/token',
    api_base_url='https://openidconnect.googleapis.com/v1/',
    issuer='https://accounts.google.com',
    jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={
        'scope': 'openid email',
        'prompt': 'select_account',
    }
)

@router.get("/login/")
@router.get("/login")
@limiter.limit("10/minute")
async def login(request: Request):
    if not _oauth_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured. Missing GOOGLE_OAUTH_CLIENT_ID or GOOGLE_OAUTH_SECRET."
        )
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    try:
        return await oauth.google.authorize_redirect(request, redirect_uri)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Cannot reach Google OAuth (DNS or network from the backend container). "
                "Retry login; on Podman/Linux, ensure container DNS works or restart the stack."
            ),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/callback/")
async def auth_callback(request: Request, session: Session = Depends(get_session)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as error:
        raise HTTPException(status_code=400, detail=error.error)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cannot reach Google OAuth (DNS or network from the backend container).",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
        
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
        session['auth_time'] = time.time()
    
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
    auth_available = _oauth_is_configured()
    return {
        "authenticated": bool(user),
        "user": user,
        "auth_available": auth_available,
        "cors_available": True
    }

@router.get("/csrf-token/")
async def csrf_token():
    return {"csrfToken": "not-needed-for-cookie-session"}
