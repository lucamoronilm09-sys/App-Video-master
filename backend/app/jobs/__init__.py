"""Coda job persistente per operazioni lunghe (render, import Drive).

Disegno volutamente semplice (app locale single-user, niente Redis):
- record JSON in data/jobs/<id>.json (sopravvivono al riavvio),
- un solo worker in-process (FIFO, un job alla volta),
- gli handler rieseguono le stesse catene agenti degli endpoint sync,
- il progress arriva dal registro app.jobs.progress (frazione 0..1).
"""
