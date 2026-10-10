from django.contrib import admin

from .models import Beleg, Board, Entitaet, Mappe, Quelle, Sicherung, Verbindung, Verlauf


class BelegInline(admin.TabularInline):
    model = Beleg
    extra = 0
    autocomplete_fields = ["quelle"]


@admin.register(Entitaet)
class EntitaetAdmin(admin.ModelAdmin):
    list_display = ["name", "typ", "status", "oeffentliche_person"]
    list_filter = ["typ", "status"]
    search_fields = ["name", "slug", "kurzbeschreibung"]


@admin.register(Quelle)
class QuelleAdmin(admin.ModelAdmin):
    list_display = ["titel", "herausgeber", "guete", "abgerufen_am"]
    search_fields = ["titel", "herausgeber", "url"]


@admin.register(Verbindung)
class VerbindungAdmin(admin.ModelAdmin):
    list_display = ["__str__", "aussageart", "status", "start", "ende", "aktuell"]
    list_filter = ["typ", "aussageart", "status"]
    autocomplete_fields = ["von", "nach"]
    inlines = [BelegInline]


class MappeInline(admin.TabularInline):
    model = Mappe
    fk_name = "board"
    extra = 0


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    inlines = [MappeInline]
    list_display = ["titel", "slug", "oeffentlich"]


@admin.register(Verlauf)
class VerlaufAdmin(admin.ModelAdmin):
    list_display = ["zeitpunkt", "objekt_art", "objekt_id", "aktion", "nutzer"]
    list_filter = ["objekt_art", "aktion"]
    readonly_fields = [f.name for f in Verlauf._meta.fields]


@admin.register(Sicherung)
class SicherungAdmin(admin.ModelAdmin):
    list_display = ["quelle", "art", "status", "bytes", "gesichert_am"]
    list_filter = ["art", "status"]
    readonly_fields = [f.name for f in Sicherung._meta.fields]
