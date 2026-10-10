"""Routen der Akte — gemountet unter ``/api/v1/akte/``.

Explizite ``urlpatterns`` wie in ``events/urls.py``; feste Pfade vor den Slugs.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("entitaeten/", views.EntitaetListeView.as_view(), name="akte-entitaeten"),
    path("entitaeten/<int:pk>/", views.EntitaetDetailView.as_view(), name="akte-entitaet"),
    path("quellen/", views.QuelleListeView.as_view(), name="akte-quellen"),
    path("quellen/aus-datei/", views.QuelleAusDateiView.as_view(), name="akte-quelle-aus-datei"),
    path("quellen/<int:pk>/", views.QuelleDetailView.as_view(), name="akte-quelle"),
    path("quellen/<int:pk>/sichern/", views.QuelleSichernView.as_view(), name="akte-quelle-sichern"),
    path("quellen/<int:pk>/anhang/", views.AnhangView.as_view(), name="akte-quelle-anhang"),
    path("quellen/<int:pk>/sicherungen/", views.SicherungListeView.as_view(), name="akte-sicherungen"),
    path("quellen/<int:pk>/video-lokal/", views.VideoLokalView.as_view(), name="akte-video-lokal"),
    path("sicherungen/<int:pk>/datei/", views.SicherungDateiView.as_view(), name="akte-sicherung-datei"),
    path("verbindungen/", views.VerbindungListeView.as_view(), name="akte-verbindungen"),
    path("verbindungen/<int:pk>/", views.VerbindungDetailView.as_view(), name="akte-verbindung"),
    path("weg/", views.WegView.as_view(), name="akte-weg"),
    path("export/obsidian/", views.ObsidianExportView.as_view(), name="akte-export-obsidian"),
    path("oeffentlich/<slug:slug>/", views.OeffentlicheWandView.as_view(), name="akte-oeffentlich"),
    path("boards/", views.BoardListeView.as_view(), name="akte-boards"),
    path("boards/<slug:slug>/", views.BoardDetailView.as_view(), name="akte-board"),
    path("boards/<slug:slug>/pruefung/", views.PruefungView.as_view(), name="akte-pruefung"),
    path("boards/<slug:slug>/positionen/", views.PositionenView.as_view(), name="akte-positionen"),
    path("boards/<slug:slug>/aufraeumen/", views.AufraeumenView.as_view(), name="akte-aufraeumen"),
    path(
        "boards/<slug:slug>/fahrten/aus-beschreibung/",
        views.FahrtAusBeschreibungView.as_view(),
        name="akte-fahrt-beschreibung",
    ),
    path("boards/<slug:slug>/karten/", views.KarteListeView.as_view(), name="akte-karten"),
    path("boards/<slug:slug>/karten/<int:pk>/", views.KarteDetailView.as_view(), name="akte-karte"),
    path("boards/<slug:slug>/beweise/", views.BeweisAnlegenView.as_view(), name="akte-beweis-neu"),
    path("boards/<slug:slug>/beweise/<int:pk>/", views.BeweisDetailView.as_view(), name="akte-beweis"),
    path("boards/<slug:slug>/zettel/", views.ZettelAnlegenView.as_view(), name="akte-zettel-neu"),
    path("boards/<slug:slug>/zettel/<int:pk>/", views.ZettelDetailView.as_view(), name="akte-zettel"),
    path("boards/<slug:slug>/rahmen/", views.RahmenAnlegenView.as_view(), name="akte-rahmen-neu"),
    path("boards/<slug:slug>/rahmen/<int:pk>/", views.RahmenDetailView.as_view(), name="akte-rahmen"),
    path("boards/<slug:slug>/mappen/", views.MappeAnlegenView.as_view(), name="akte-mappe-neu"),
    path("boards/<slug:slug>/mappen/<int:pk>/", views.MappeDetailView.as_view(), name="akte-mappe"),
    path("boards/<slug:slug>/fahrten/", views.FahrtAnlegenView.as_view(), name="akte-fahrt-neu"),
    path("boards/<slug:slug>/fahrten/<int:pk>/", views.FahrtDetailView.as_view(), name="akte-fahrt"),
    path(
        "boards/<slug:slug>/faeden/<int:pk>/ausblenden/",
        views.FadenAusblendenView.as_view(),
        name="akte-faden-ausblenden",
    ),
]
