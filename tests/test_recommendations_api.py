from app.main import create_app


def test_recommendations_requires_authentication():
    app=create_app();app.config.update(TESTING=True)
    response=app.test_client().get('/api/recommendations')
    assert response.status_code==401
    assert response.get_json()['error']=='authentication_required'


def test_legacy_url_also_requires_authentication():
    app=create_app();app.config.update(TESTING=True)
    response=app.test_client().get('/api/recommendations/414')
    assert response.status_code==401


def test_home_does_not_offer_id_selection():
    app=create_app();app.config.update(TESTING=True)
    page=app.test_client().get('/').get_data(as_text=True)
    assert 'id="recommendationForm"' not in page
    assert 'id="userId"' not in page
    assert 'Descubrir mi Top 10' not in page
