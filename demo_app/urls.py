from django.urls import path
from . import views

urlpatterns = [
    path("authors/", views.AuthorListView.as_view(), name="author-list"),
    path("authors/<str:pk>/", views.AuthorDetailView.as_view(), name="author-detail"),
    path("posts/", views.PostListView.as_view(), name="post-list"),
    path("posts/<str:pk>/", views.PostDetailView.as_view(), name="post-detail"),
    path("posts/<str:post_pk>/comments/", views.CommentCreateView.as_view(), name="comment-create"),
    path("comments/<str:pk>/", views.CommentDeleteView.as_view(), name="comment-delete"),
]
