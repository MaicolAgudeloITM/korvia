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


def test_la_interfaz_no_depende_de_internet_ni_escribe_html_directo(client) -> None:
    html = client.get("/").text
    script = client.get("/app.js").text

    assert "http://" not in html
    assert "https://" not in html
    assert "innerHTML" not in script
    assert "fetch(" in script
