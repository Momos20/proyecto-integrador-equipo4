from app.main import create_app


def test_interactions_reject_anonymous_post():
    app=create_app();app.config.update(TESTING=True)
    response=app.test_client().post('/api/interactions', json={"movie_id":2571,"interaction_type":"like"})
    assert response.status_code==401
    assert response.get_json()['error']=='authentication_required'


def test_interactions_reject_anonymous_read():
    app=create_app();app.config.update(TESTING=True)
    response=app.test_client().get('/api/interactions')
    assert response.status_code==401
