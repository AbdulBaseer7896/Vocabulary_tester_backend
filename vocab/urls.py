from django.urls import path

from . import views

urlpatterns = [
    path("decks/", views.decks),
    path("decks/<int:pk>/", views.deck_detail),
    path("decks/<int:pk>/csv/", views.deck_csv),
    path("decks/<int:pk>/sessions/", views.deck_sessions),
    path("decks/<int:pk>/marks/reset/", views.reset_marks),
    path("words/<int:pk>/mark/", views.word_mark),
    path("sessions/", views.create_session),
    # Listed before the <int:pk> routes so "history" is not read as an id.
    path("sessions/history/", views.session_history),
    path("sessions/<int:pk>/", views.session_detail),
    path("sessions/<int:pk>/answer/", views.submit_answer),
    path("sessions/<int:pk>/report/", views.session_report),
    path("sessions/<int:pk>/resume/", views.resume_session),
    path("sessions/<int:pk>/finish/", views.finish_session),
]
