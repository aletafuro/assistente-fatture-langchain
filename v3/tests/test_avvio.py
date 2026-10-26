"""Controllo della configurazione all'avvio del bot (fail fast con un messaggio chiaro)."""

import avvio


def test_manca_la_configurazione(monkeypatch, capsys):
    for nome in [*avvio.OBBLIGATORIE, *avvio.AUTORIZZAZIONE]:
        monkeypatch.delenv(nome, raising=False)
    assert avvio.controlla() is False
    uscita = capsys.readouterr().out
    assert "TELEGRAM_BOT_TOKEN" in uscita and "TELEGRAM_GRUPPI_AUTORIZZATI" in uscita


def test_configurazione_completa(monkeypatch):
    for nome in avvio.OBBLIGATORIE:
        monkeypatch.setenv(nome, "valore-di-prova")
    monkeypatch.delenv("TELEGRAM_UTENTI_AUTORIZZATI", raising=False)
    monkeypatch.setenv("TELEGRAM_GRUPPI_AUTORIZZATI", "-1001234567890")      # basta il gruppo
    assert avvio.controlla() is True
