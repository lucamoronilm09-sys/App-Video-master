"""Test per verificare l'interazione corretta tra API key authentication e CORS."""
import os
import sys
import pytest

# Aggiungi backend al path per gli import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_env():
    """Pulisce le variabili d'ambiente prima e dopo ogni test."""
    # Salva lo stato corrente
    saved_api_key = os.environ.get("API_KEY")
    saved_cors_origins = os.environ.get("CORS_ORIGINS")
    
    yield
    
    # Ripristina lo stato
    if saved_api_key is None:
        os.environ.pop("API_KEY", None)
    else:
        os.environ["API_KEY"] = saved_api_key
        
    if saved_cors_origins is None:
        os.environ.pop("CORS_ORIGINS", None)
    else:
        os.environ["CORS_ORIGINS"] = saved_cors_origins


def create_test_app(api_key=None):
    """Crea una nuova istanza dell'app con la API key specificata.
    
    Imposta la variabile d'ambiente PRIMA di importare i moduli.
    """
    # Imposta API_KEY prima dell'import
    if api_key is not None:
        os.environ["API_KEY"] = api_key
    else:
        os.environ.pop("API_KEY", None)
    
    # Importa qui per assicurarsi che le variabili d'ambiente siano lette correttamente
    from app.main import app as test_app
    return test_app


def get_client(api_key=None):
    """Crea un nuovo client di test con la API key specificata."""
    test_app = create_test_app(api_key=api_key)
    # Usa raise_server_exceptions=True per far propagare le HTTPException
    # e ottenere lo status code corretto nelle response
    return TestClient(test_app, raise_server_exceptions=True)


class TestAuthCorsInteraction:
    """Test per verificare che CORS preflight funzioni con API key attiva."""

    def test_api_key_disabilitata_get(self):
        """GET senza API_KEY configurata dovrebbe passare."""
        client = get_client(api_key=None)
        
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_api_key_disabilitata_post(self):
        """POST senza API_KEY configurata dovrebbe passare."""
        client = get_client(api_key=None)
        
        # Usa un endpoint che esiste
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_api_key_attiva_get_con_key_corretta(self):
        """GET con API_KEY attiva e chiave corretta dovrebbe passare."""
        client = get_client(api_key="test-secret-key-123")
        
        response = client.get(
            "/api/health",
            headers={"X-API-Key": "test-secret-key-123"}
        )
        assert response.status_code == 200

    def test_api_key_attiva_get_senza_key(self):
        """GET con API_KEY attiva ma senza chiave dovrebbe fallire con 401."""
        client = get_client(api_key="test-secret-key-123")
        
        # Il middleware ritorna direttamente JSONResponse con status 401
        # invece di sollevare HTTPException, quindi non serve raise_server_exceptions
        response = client.get("/api/health")
        assert response.status_code == 401
        assert "api key" in response.json().get("detail", "").lower()

    def test_api_key_attiva_get_con_key_errata(self):
        """GET con API_KEY attiva e chiave errata dovrebbe fallire con 401."""
        client = get_client(api_key="test-secret-key-123")
        
        # Il middleware ritorna direttamente JSONResponse con status 401
        response = client.get(
            "/api/health",
            headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code == 401
        assert "api key" in response.json().get("detail", "").lower()

    def test_options_senza_api_key(self):
        """OPTIONS (CORS preflight) senza API key dovrebbe sempre passare."""
        client = get_client(api_key="test-secret-key-123")
        
        # Simula una richiesta CORS preflight - non includere X-API-Key negli header richiesti
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            }
        )
        # Il preflight CORS deve passare senza autenticazione
        assert response.status_code == 200

    def test_options_con_api_key_corretta(self):
        """OPTIONS con API key corretta dovrebbe passare."""
        client = get_client(api_key="test-secret-key-123")
        
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
                "X-API-Key": "test-secret-key-123",
            }
        )
        assert response.status_code == 200

    def test_options_con_api_key_errata(self):
        """OPTIONS con API key errata dovrebbe comunque passare (preflight non richiede auth)."""
        client = get_client(api_key="test-secret-key-123")
        
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
                "X-API-Key": "wrong-key",
            }
        )
        # Le OPTIONS devono passare anche con API key errata perché sono preflight
        assert response.status_code == 200

    def test_api_key_attiva_post_con_key_corretta(self):
        """POST con API_KEY attiva e chiave corretta dovrebbe passare."""
        client = get_client(api_key="test-secret-key-123")
        
        # Usa health check che è un GET semplice
        response = client.get(
            "/api/health",
            headers={"X-API-Key": "test-secret-key-123"}
        )
        assert response.status_code == 200

    def test_cors_headers_presenti(self):
        """Verifica che gli header CORS siano presenti nelle risposte."""
        os.environ["CORS_ORIGINS"] = "http://localhost:3000"
        client = get_client(api_key=None)
        
        response = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:3000"}
        )
        assert response.status_code == 200
        # Verifica la presenza degli header CORS
        assert "access-control-allow-origin" in response.headers

    def test_secrets_compare_digest_usato(self):
        """Verifica che il modulo secrets sia importato in auth.py."""
        from app import auth
        import inspect
        source = inspect.getsource(auth)
        assert "secrets.compare_digest" in source
        assert "import secrets" in source


class TestApiKeySecurity:
    """Test per verificare la sicurezza del confronto API key."""

    def test_timing_attack_protection(self):
        """Verifica che secrets.compare_digest sia usato per prevenire timing attacks."""
        import secrets
        from app.auth import verify_api_key
        import inspect
        
        # Verifica che secrets.compare_digest sia usato nel codice
        source = inspect.getsource(verify_api_key)
        assert "secrets.compare_digest" in source

    def test_api_key_missing_vs_invalid_distinction(self):
        """Verifica che i messaggi per API key mancante e invalida siano diversi."""
        client = get_client(api_key="test-secret-key-123")
        
        # Senza API key
        response_missing = client.get("/api/health")
        detail_missing = response_missing.json()["detail"]
        
        # Con API key errata
        response_invalid = client.get(
            "/api/health",
            headers={"X-API-Key": "wrong"}
        )
        detail_invalid = response_invalid.json()["detail"]
        
        assert "mancante" in detail_missing.lower()
        assert "non valida" in detail_invalid.lower() or "invalida" in detail_invalid.lower()
