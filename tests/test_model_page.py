from app.main import create_app


def test_home_distinguishes_uploaded_models_from_demo_serving():
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "A9_sin_id" in page
    assert "A0_base" in page
    assert "Checkpoint disponible" in page
    assert "Popularit" in page
    assert "0,1390" in page
    assert "0,0915" in page
    assert "modelo GraphSAGE" in page
    assert 'id="servingNotice"' in page
    assert ">LIVE<" not in page
