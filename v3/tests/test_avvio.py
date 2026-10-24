"""Controllo della configurazione all'avvio del bot (fail fast con un messaggio chiaro)."""

import avvio


def test_manca_la_configurazione(monkeypatch, capsys):
    for nome in avvio.OBBLIGATORIE:
        monkeypatch.delenv(nome, raising=False)
    assert avvio.controlla() is False
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().out


def test_configurazione_completa(monkeypatch):
    for nome in avvio.OBBLIGATORIE:
        monkeypatch.setenv(nome, "valore-di-prova")
    assert avvio.controlla() is True
