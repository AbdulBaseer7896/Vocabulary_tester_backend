from django.contrib import admin

from .models import Answer, Deck, TestSession, Word


class WordInline(admin.TabularInline):
    model = Word
    extra = 0
    fields = ("position", "word", "synonym1", "synonym2", "antonym1", "antonym2", "mark")


@admin.register(Deck)
class DeckAdmin(admin.ModelAdmin):
    list_display = ("name", "word_count", "created_at", "updated_at")
    inlines = [WordInline]

    @admin.display(description="Words")
    def word_count(self, obj):
        return obj.words.count()


@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ("word", "deck", "mark", "marked_at")
    list_filter = ("deck", "mark")
    search_fields = ("word", "synonym1", "synonym2", "antonym1", "antonym2")


class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 0
    readonly_fields = ("question_index", "slot", "given", "expected", "is_correct", "plays")


@admin.register(TestSession)
class TestSessionAdmin(admin.ModelAdmin):
    list_display = ("deck", "status", "reveal_mode", "sort_order", "current_index", "started_at")
    list_filter = ("status", "reveal_mode", "deck")
    inlines = [AnswerInline]
