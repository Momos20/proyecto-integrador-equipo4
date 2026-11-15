"""Aisla el acceso a MovieLens con monkeypatch, sin requerir base real en la prueba."""
from app.main import create_app
from app.services import auth_service
from app.routes import api


def test_login_session_and_private_recommendations(monkeypatch):
    account={"account_id":1,"username":"cine414","movielens_user_id":414}
    monkeypatch.setattr(api,'verify_credentials',lambda username,password:account if username=='cine414' and password=='example' else None)
    monkeypatch.setattr(api,'get_account',lambda:account if auth_service.session.get('account_id')==1 else None)
    monkeypatch.setattr(auth_service,'get_account',lambda:account if auth_service.session.get('account_id')==1 else None)
    app=create_app();app.config.update(TESTING=True)
    client=app.test_client()
    token=client.get('/api/auth/me').get_json()['csrf_token']
    response=client.post('/api/auth/login',json={'username':'cine414','password':'example'},headers={'X-CSRF-Token':token})
    assert response.status_code==200
    assert response.get_json()['user']['movielens_user_id']==414
    assert client.get('/api/recommendations/123').status_code==403
    assert client.get('/api/interactions/123').status_code==403
    assert client.post('/api/interactions',json={'movie_id':2571,'interaction_type':'like','user_id':123},headers={'X-CSRF-Token':response.get_json()['csrf_token']}).status_code==403
    assert client.post('/api/auth/logout',headers={'X-CSRF-Token':response.get_json()['csrf_token']}).status_code==200
    assert client.get('/api/recommendations').status_code==401
