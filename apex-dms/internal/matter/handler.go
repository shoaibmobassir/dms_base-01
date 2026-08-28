package matter

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/apex-chambers/dms/internal/ctxutil"
	"github.com/apex-chambers/dms/internal/model"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
)

type Handler struct {
	repo *Repository
}

func NewHandler(repo *Repository) *Handler {
	return &Handler{repo: repo}
}

// Routes returns a chi.Router for matter routes.
func (h *Handler) Routes() chi.Router {
	r := chi.NewRouter()

	// Clients
	r.Get("/clients", h.ListClients)
	r.Post("/clients", h.CreateClient)

	// Practice areas
	r.Get("/practice-areas", h.ListPracticeAreas)
	r.Post("/practice-areas", h.CreatePracticeArea)

	// Matters
	r.Get("/", h.ListMatters)
	r.Post("/", h.CreateMatter)
	r.Get("/{matterID}", h.GetMatter)
	r.Patch("/{matterID}/status", h.UpdateStatus)
	r.Delete("/{matterID}", h.DeleteMatter)
	r.Get("/{matterID}/members", h.ListMatterMembers)
	r.Post("/{matterID}/members", h.AddMatterMember)

	// Documents
	r.Get("/{matterID}/documents", h.ListMatterDocuments)

	return r
}

// --- Client handlers ---

func (h *Handler) ListClients(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	clients, err := h.repo.ListClients(r.Context(), firmID)
	if err != nil {
		writeErr(w, 500, "failed to list clients")
		return
	}
	if clients == nil {
		clients = []model.Client{}
	}
	writeJSON(w, 200, map[string]any{"clients": clients})
}

func (h *Handler) CreateClient(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	var body struct {
		Name       string  `json:"name"`
		ClientType string  `json:"client_type"`
		Email      *string `json:"contact_email"`
		Phone      *string `json:"contact_phone"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Name == "" {
		writeErr(w, 400, "name and client_type required")
		return
	}
	if body.ClientType == "" {
		body.ClientType = "organisation"
	}
	client, err := h.repo.CreateClient(r.Context(), firmID, body.Name, body.ClientType, body.Email, body.Phone)
	if err != nil {
		slog.Error("create client", "error", err)
		writeErr(w, 500, "failed to create client")
		return
	}
	writeJSON(w, 201, client)
}

// --- Practice Area handlers ---

func (h *Handler) ListPracticeAreas(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	areas, err := h.repo.ListPracticeAreas(r.Context(), firmID)
	if err != nil {
		writeErr(w, 500, "failed to list practice areas")
		return
	}
	if areas == nil {
		areas = []model.PracticeArea{}
	}
	writeJSON(w, 200, map[string]any{"practice_areas": areas})
}

func (h *Handler) CreatePracticeArea(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	var body struct {
		Name  string `json:"name"`
		Color string `json:"color"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Name == "" {
		writeErr(w, 400, "name required")
		return
	}
	if body.Color == "" {
		body.Color = "#6366f1"
	}
	area, err := h.repo.CreatePracticeArea(r.Context(), firmID, body.Name, body.Color)
	if err != nil {
		slog.Error("create practice area", "error", err)
		writeErr(w, 500, "failed to create practice area")
		return
	}
	writeJSON(w, 201, area)
}

// --- Matter handlers ---

func (h *Handler) ListMatters(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	status := r.URL.Query().Get("status")
	matters, err := h.repo.ListMatters(r.Context(), firmID, status)
	if err != nil {
		slog.Error("list matters", "error", err)
		writeErr(w, 500, "failed to list matters")
		return
	}
	if matters == nil {
		matters = []model.Matter{}
	}
	writeJSON(w, 200, map[string]any{"matters": matters})
}

func (h *Handler) CreateMatter(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	userID := ctxutil.UserIDFromCtx(r.Context())
	var body struct {
		Title          string     `json:"title"`
		Description    *string    `json:"description"`
		PracticeAreaID *uuid.UUID `json:"practice_area_id"`
		ClientID       *uuid.UUID `json:"client_id"`
		Status         string     `json:"status"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Title == "" {
		writeErr(w, 400, "title required")
		return
	}
	if body.Status == "" {
		body.Status = "active"
	}

	code, err := h.repo.GenerateMatterCode(r.Context(), firmID, "APX")
	if err != nil {
		slog.Error("generate matter code", "error", err)
		writeErr(w, 500, "failed to generate code")
		return
	}

	m := &model.Matter{
		FirmID:         firmID,
		MatterCode:     code,
		Title:          body.Title,
		Description:    body.Description,
		PracticeAreaID: body.PracticeAreaID,
		ClientID:       body.ClientID,
		Status:         model.MatterStatus(body.Status),
		LeadUserID:     &userID,
	}
	if err := h.repo.CreateMatter(r.Context(), m); err != nil {
		slog.Error("create matter", "error", err)
		writeErr(w, 500, "failed to create matter")
		return
	}

	// Auto-add creator as lead
	h.repo.AddMatterMember(r.Context(), m.MatterID, userID, "lead", userID)

	writeJSON(w, 201, m)
}

func (h *Handler) GetMatter(w http.ResponseWriter, r *http.Request) {
	matterID, err := uuid.Parse(chi.URLParam(r, "matterID"))
	if err != nil {
		writeErr(w, 400, "invalid matter ID")
		return
	}
	m, err := h.repo.GetMatter(r.Context(), matterID)
	if err != nil || m == nil {
		writeErr(w, 404, "matter not found")
		return
	}
	writeJSON(w, 200, m)
}

func (h *Handler) UpdateStatus(w http.ResponseWriter, r *http.Request) {
	matterID, err := uuid.Parse(chi.URLParam(r, "matterID"))
	if err != nil {
		writeErr(w, 400, "invalid matter ID")
		return
	}
	var body struct {
		Status string `json:"status"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Status == "" {
		writeErr(w, 400, "status required")
		return
	}
	if err := h.repo.UpdateMatterStatus(r.Context(), matterID, model.MatterStatus(body.Status)); err != nil {
		writeErr(w, 500, "failed to update status")
		return
	}
	writeJSON(w, 200, map[string]string{"status": "updated"})
}

func (h *Handler) DeleteMatter(w http.ResponseWriter, r *http.Request) {
	matterID, err := uuid.Parse(chi.URLParam(r, "matterID"))
	if err != nil {
		writeErr(w, 400, "invalid matter ID")
		return
	}
	if err := h.repo.DeleteMatter(r.Context(), matterID); err != nil {
		writeErr(w, 500, "failed to delete matter")
		return
	}
	writeJSON(w, 200, map[string]string{"status": "deleted"})
}

// --- Matter Members ---

func (h *Handler) ListMatterMembers(w http.ResponseWriter, r *http.Request) {
	matterID, err := uuid.Parse(chi.URLParam(r, "matterID"))
	if err != nil {
		writeErr(w, 400, "invalid matter ID")
		return
	}
	members, err := h.repo.ListMatterMembers(r.Context(), matterID)
	if err != nil {
		writeErr(w, 500, "failed to list members")
		return
	}
	if members == nil {
		members = []model.MatterMember{}
	}
	writeJSON(w, 200, map[string]any{"members": members})
}

func (h *Handler) AddMatterMember(w http.ResponseWriter, r *http.Request) {
	matterID, _ := uuid.Parse(chi.URLParam(r, "matterID"))
	assignedBy := ctxutil.UserIDFromCtx(r.Context())
	var body struct {
		UserID     uuid.UUID `json:"user_id"`
		MatterRole string    `json:"matter_role"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	if body.MatterRole == "" {
		body.MatterRole = "contributor"
	}
	h.repo.AddMatterMember(r.Context(), matterID, body.UserID, body.MatterRole, assignedBy)
	writeJSON(w, 201, map[string]string{"status": "added"})
}

// --- Documents (per matter) ---

func (h *Handler) ListMatterDocuments(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	matterID, _ := uuid.Parse(chi.URLParam(r, "matterID"))
	docs, err := h.repo.ListDocuments(r.Context(), firmID, &matterID)
	if err != nil {
		writeErr(w, 500, "failed to list documents")
		return
	}
	if docs == nil {
		docs = []model.Document{}
	}
	writeJSON(w, 200, map[string]any{"documents": docs})
}

// --- Global document + conversation routes ---

func (h *Handler) DocumentRoutes() chi.Router {
	r := chi.NewRouter()
	r.Get("/", h.ListAllDocuments)
	return r
}

func (h *Handler) ListAllDocuments(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	docs, err := h.repo.ListDocuments(r.Context(), firmID, nil)
	if err != nil {
		writeErr(w, 500, "failed to list documents")
		return
	}
	if docs == nil {
		docs = []model.Document{}
	}
	writeJSON(w, 200, map[string]any{"documents": docs})
}

func (h *Handler) ConversationRoutes() chi.Router {
	r := chi.NewRouter()
	r.Get("/", h.ListConversations)
	r.Post("/", h.CreateConversation)
	r.Get("/{convID}/messages", h.ListMessages)
	r.Post("/{convID}/messages", h.SendMessage)
	return r
}

func (h *Handler) ListConversations(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	userID := ctxutil.UserIDFromCtx(r.Context())
	convs, err := h.repo.ListConversations(r.Context(), firmID, userID)
	if err != nil {
		writeErr(w, 500, "failed to list conversations")
		return
	}
	if convs == nil {
		convs = []model.Conversation{}
	}
	writeJSON(w, 200, map[string]any{"conversations": convs})
}

func (h *Handler) CreateConversation(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	userID := ctxutil.UserIDFromCtx(r.Context())
	var body struct {
		Title    *string    `json:"title"`
		MatterID *uuid.UUID `json:"matter_id"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	c := &model.Conversation{
		FirmID:   firmID,
		UserID:   userID,
		MatterID: body.MatterID,
		Title:    body.Title,
		ModelID:  "gemini-2.0-flash",
	}
	if err := h.repo.CreateConversation(r.Context(), c); err != nil {
		writeErr(w, 500, "failed to create conversation")
		return
	}
	writeJSON(w, 201, c)
}

func (h *Handler) ListMessages(w http.ResponseWriter, r *http.Request) {
	convID, _ := uuid.Parse(chi.URLParam(r, "convID"))
	msgs, err := h.repo.ListMessages(r.Context(), convID)
	if err != nil {
		writeErr(w, 500, "failed to list messages")
		return
	}
	if msgs == nil {
		msgs = []model.Message{}
	}
	writeJSON(w, 200, map[string]any{"messages": msgs})
}

func (h *Handler) SendMessage(w http.ResponseWriter, r *http.Request) {
	convID, _ := uuid.Parse(chi.URLParam(r, "convID"))
	var body struct {
		Content string `json:"content"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	if body.Content == "" {
		writeErr(w, 400, "content required")
		return
	}

	// Store user message
	userMsg := &model.Message{
		ConversationID: convID,
		Role:           "user",
		Content:        body.Content,
	}
	h.repo.CreateMessage(r.Context(), userMsg)

	// Mock AI response (in production this calls LLM)
	aiMsg := &model.Message{
		ConversationID: convID,
		Role:           "assistant",
		Content:        "I've analyzed your query. Based on the documents in this matter, here's what I found:\n\n**Summary:** This is a placeholder response. In production, this would use the Graph RAG pipeline to retrieve relevant document chunks, traverse the knowledge graph for entity relationships, and generate a grounded, cited response.\n\n*Note: Connect LLM provider (Gemini/Groq) to enable real AI responses.*",
	}
	h.repo.CreateMessage(r.Context(), aiMsg)

	writeJSON(w, 201, map[string]any{
		"user_message":      userMsg,
		"assistant_message": aiMsg,
	})
}

// --- helpers ---

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}

func writeErr(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
