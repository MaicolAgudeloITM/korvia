def test_la_portada_de_la_interfaz_se_sirve(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "KORVIA" in response.text
    assert "/app.js" in response.text
    assert "/styles.css" in response.text
    accept = response.text.split('accept="')[1].split('"')[0]
    for extension in (".pdf", ".pptx", ".odt", ".csv", ".json", ".png"):
        assert extension in accept
    assert response.headers["X-Frame-Options"] == "DENY"


def test_los_archivos_de_la_interfaz_se_sirven(client) -> None:
    script = client.get("/app.js")
    styles = client.get("/styles.css")

    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]


def test_el_rol_de_miembro_no_dice_solo_lectura(client) -> None:
    html = client.get("/").text
    script = client.get("/app.js").text

    assert "Solo lectura" not in script
    assert "Solo lectura" not in html
    assert "Miembro · puede preguntar y ejecutar agentes" in script
    assert 'id="space-form"' in html
    assert 'id="upload-form"' in html
    assert '$("space-form").hidden = esMiembro;' in script
    assert '$("upload-form").hidden = esMiembro;' in script
    assert '"Ejecutar"' in script


def test_el_selector_de_areas_no_ofrece_todas_las_areas(client) -> None:
    script = client.get("/app.js").text

    assert "Todas las áreas" not in script


def test_la_interfaz_convierte_los_errores_en_texto(client) -> None:
    script = client.get("/app.js").text

    assert "function detailText" in script
    assert "Array.isArray(detail)" in script
    assert "[object Object]" not in script


def test_la_interfaz_no_depende_de_internet_ni_escribe_html_directo(client) -> None:
    html = client.get("/").text
    script = client.get("/app.js").text

    assert "http://" not in html
    assert "https://" not in html
    assert "innerHTML" not in script
    assert "fetch(" in script
