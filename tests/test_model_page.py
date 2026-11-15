from app.main import create_app


def test_home_shows_only_a9_as_the_selected_model():
    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().get("/")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "A9_sin_id" in page
    assert "A0_base" not in page
    assert "Modelo seleccionado" in page
    assert "Integración pendiente" in page
    assert "0,1390" in page
    assert "0,0915" in page
    assert "validación registrada" in page
    assert "Top-10 de demostración" in page
    assert 'id="servingNotice"' in page
    assert ">LIVE<" not in page
