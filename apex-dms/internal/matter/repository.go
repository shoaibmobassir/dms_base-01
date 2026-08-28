package matter

import (
	"context"
	"fmt"
	"time"

	"github.com/apex-chambers/dms/internal/model"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Repository struct {
	pool *pgxpool.Pool
}

func NewRepository(pool *pgxpool.Pool) *Repository {
	return &Repository{pool: pool}
}

// --- Clients ---

func (r *Repository) CreateClient(ctx context.Context, firmID uuid.UUID, name, clientType string, email, phone *string) (*model.Client, error) {
	c := &model.Client{}
	err := r.pool.QueryRow(ctx, `
		INSERT INTO clients (firm_id, name, client_type, contact_email, contact_phone)
		VALUES ($1, $2, $3, $4, $5)
		RETURNING client_id, firm_id, name, client_type, contact_email, contact_phone, notes, created_at, updated_at
	`, firmID, name, clientType, email, phone).Scan(
		&c.ClientID, &c.FirmID, &c.Name, &c.ClientType, &c.ContactEmail, &c.ContactPhone, &c.Notes, &c.CreatedAt, &c.UpdatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("create client: %w", err)
	}
	return c, nil
}

func (r *Repository) ListClients(ctx context.Context, firmID uuid.UUID) ([]model.Client, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT client_id, firm_id, name, client_type, contact_email, contact_phone, notes, created_at, updated_at
		FROM clients WHERE firm_id = $1 ORDER BY name ASC
	`, firmID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var clients []model.Client
	for rows.Next() {
		var c model.Client
		if err := rows.Scan(&c.ClientID, &c.FirmID, &c.Name, &c.ClientType, &c.ContactEmail, &c.ContactPhone, &c.Notes, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, err
		}
		clients = append(clients, c)
	}
	return clients, nil
}

// --- Practice Areas ---

func (r *Repository) CreatePracticeArea(ctx context.Context, firmID uuid.UUID, name, color string) (*model.PracticeArea, error) {
	pa := &model.PracticeArea{}
	err := r.pool.QueryRow(ctx, `
		INSERT INTO practice_areas (firm_id, name, color)
		VALUES ($1, $2, $3)
		RETURNING area_id, firm_id, name, color, sort_order
	`, firmID, name, color).Scan(&pa.AreaID, &pa.FirmID, &pa.Name, &pa.Color, &pa.SortOrder)
	if err != nil {
		return nil, fmt.Errorf("create practice area: %w", err)
	}
	return pa, nil
}

func (r *Repository) ListPracticeAreas(ctx context.Context, firmID uuid.UUID) ([]model.PracticeArea, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT area_id, firm_id, name, color, sort_order
		FROM practice_areas WHERE firm_id = $1 ORDER BY sort_order, name
	`, firmID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var areas []model.PracticeArea
	for rows.Next() {
		var pa model.PracticeArea
		if err := rows.Scan(&pa.AreaID, &pa.FirmID, &pa.Name, &pa.Color, &pa.SortOrder); err != nil {
			return nil, err
		}
		areas = append(areas, pa)
	}
	return areas, nil
}

// --- Matters ---

func (r *Repository) GenerateMatterCode(ctx context.Context, firmID uuid.UUID, prefix string) (string, error) {
	var num int
	err := r.pool.QueryRow(ctx, `
		INSERT INTO matter_code_sequences (firm_id, last_number)
		VALUES ($1, 1)
		ON CONFLICT (firm_id) DO UPDATE SET last_number = matter_code_sequences.last_number + 1
		RETURNING last_number
	`, firmID).Scan(&num)
	if err != nil {
		return "", fmt.Errorf("generate code: %w", err)
	}
	year := time.Now().Year()
	return fmt.Sprintf("%s-%d-%04d", prefix, year, num), nil
}

func (r *Repository) CreateMatter(ctx context.Context, m *model.Matter) error {
	return r.pool.QueryRow(ctx, `
		INSERT INTO matters (firm_id, matter_code, title, description, practice_area_id, client_id, status, lead_user_id, metadata)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		RETURNING matter_id, created_at, updated_at
	`, m.FirmID, m.MatterCode, m.Title, m.Description, m.PracticeAreaID, m.ClientID, m.Status, m.LeadUserID, m.Metadata,
	).Scan(&m.MatterID, &m.CreatedAt, &m.UpdatedAt)
}

func (r *Repository) GetMatter(ctx context.Context, matterID uuid.UUID) (*model.Matter, error) {
	m := &model.Matter{}
	err := r.pool.QueryRow(ctx, `
		SELECT m.matter_id, m.firm_id, m.matter_code, m.title, m.description,
		       m.practice_area_id, m.client_id, m.status, m.lead_user_id, m.metadata,
		       m.created_at, m.updated_at, m.closed_at, m.deleted_at,
		       COALESCE(c.name, ''), COALESCE(pa.name, ''), COALESCE(u.display_name, ''),
		       (SELECT count(*) FROM documents d WHERE d.matter_id = m.matter_id AND d.deleted_at IS NULL),
		       (SELECT count(*) FROM matter_members mm WHERE mm.matter_id = m.matter_id)
		FROM matters m
		LEFT JOIN clients c ON c.client_id = m.client_id
		LEFT JOIN practice_areas pa ON pa.area_id = m.practice_area_id
		LEFT JOIN users u ON u.user_id = m.lead_user_id
		WHERE m.matter_id = $1 AND m.deleted_at IS NULL
	`, matterID).Scan(
		&m.MatterID, &m.FirmID, &m.MatterCode, &m.Title, &m.Description,
		&m.PracticeAreaID, &m.ClientID, &m.Status, &m.LeadUserID, &m.Metadata,
		&m.CreatedAt, &m.UpdatedAt, &m.ClosedAt, &m.DeletedAt,
		&m.ClientName, &m.PracticeAreaName, &m.LeadName,
		&m.DocumentCount, &m.MemberCount,
	)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("get matter: %w", err)
	}
	return m, nil
}

func (r *Repository) ListMatters(ctx context.Context, firmID uuid.UUID, status string) ([]model.Matter, error) {
	query := `
		SELECT m.matter_id, m.firm_id, m.matter_code, m.title, m.description,
		       m.practice_area_id, m.client_id, m.status, m.lead_user_id, m.metadata,
		       m.created_at, m.updated_at, m.closed_at, m.deleted_at,
		       COALESCE(c.name, ''), COALESCE(pa.name, ''), COALESCE(u.display_name, ''),
		       (SELECT count(*) FROM documents d WHERE d.matter_id = m.matter_id AND d.deleted_at IS NULL),
		       (SELECT count(*) FROM matter_members mm WHERE mm.matter_id = m.matter_id)
		FROM matters m
		LEFT JOIN clients c ON c.client_id = m.client_id
		LEFT JOIN practice_areas pa ON pa.area_id = m.practice_area_id
		LEFT JOIN users u ON u.user_id = m.lead_user_id
		WHERE m.firm_id = $1 AND m.deleted_at IS NULL
	`
	args := []any{firmID}
	if status != "" {
		query += " AND m.status = $2"
		args = append(args, status)
	}
	query += " ORDER BY m.updated_at DESC"

	rows, err := r.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var matters []model.Matter
	for rows.Next() {
		var m model.Matter
		if err := rows.Scan(
			&m.MatterID, &m.FirmID, &m.MatterCode, &m.Title, &m.Description,
			&m.PracticeAreaID, &m.ClientID, &m.Status, &m.LeadUserID, &m.Metadata,
			&m.CreatedAt, &m.UpdatedAt, &m.ClosedAt, &m.DeletedAt,
			&m.ClientName, &m.PracticeAreaName, &m.LeadName,
			&m.DocumentCount, &m.MemberCount,
		); err != nil {
			return nil, err
		}
		matters = append(matters, m)
	}
	return matters, nil
}

func (r *Repository) UpdateMatterStatus(ctx context.Context, matterID uuid.UUID, status model.MatterStatus) error {
	query := `UPDATE matters SET status = $2, updated_at = now()`
	if status == model.MatterStatusClosed {
		query += ", closed_at = now()"
	}
	query += " WHERE matter_id = $1"
	_, err := r.pool.Exec(ctx, query, matterID, string(status))
	return err
}

func (r *Repository) DeleteMatter(ctx context.Context, matterID uuid.UUID) error {
	_, err := r.pool.Exec(ctx, `UPDATE matters SET deleted_at = now() WHERE matter_id = $1`, matterID)
	return err
}

// --- Matter Members ---

func (r *Repository) AddMatterMember(ctx context.Context, matterID, userID uuid.UUID, role string, assignedBy uuid.UUID) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO matter_members (matter_id, user_id, matter_role, assigned_by)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (matter_id, user_id) DO UPDATE SET matter_role = $3
	`, matterID, userID, role, assignedBy)
	return err
}

func (r *Repository) ListMatterMembers(ctx context.Context, matterID uuid.UUID) ([]model.MatterMember, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT mm.matter_id, mm.user_id, mm.matter_role, mm.assigned_at,
		       u.display_name, u.email, u.avatar_url
		FROM matter_members mm
		JOIN users u ON u.user_id = mm.user_id
		WHERE mm.matter_id = $1
		ORDER BY mm.assigned_at
	`, matterID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var members []model.MatterMember
	for rows.Next() {
		var m model.MatterMember
		if err := rows.Scan(&m.MatterID, &m.UserID, &m.MatterRole, &m.AssignedAt, &m.DisplayName, &m.Email, &m.AvatarURL); err != nil {
			return nil, err
		}
		members = append(members, m)
	}
	return members, nil
}

// --- Documents ---

func (r *Repository) CreateDocument(ctx context.Context, d *model.Document) error {
	return r.pool.QueryRow(ctx, `
		INSERT INTO documents (firm_id, matter_id, title, filename, document_type, tags, created_by)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		RETURNING document_id, created_at, updated_at
	`, d.FirmID, d.MatterID, d.Title, d.Filename, d.DocumentType, d.Tags, d.CreatedBy,
	).Scan(&d.DocumentID, &d.CreatedAt, &d.UpdatedAt)
}

func (r *Repository) CreateDocumentVersion(ctx context.Context, v *model.DocumentVersion) error {
	return r.pool.QueryRow(ctx, `
		INSERT INTO document_versions (document_id, version_number, storage_key, file_size, mime_type, content_hash, uploaded_by)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		RETURNING version_id, uploaded_at
	`, v.DocumentID, v.VersionNumber, v.StorageKey, v.FileSize, v.MimeType, v.ContentHash, v.UploadedBy,
	).Scan(&v.VersionID, &v.UploadedAt)
}

func (r *Repository) ListDocuments(ctx context.Context, firmID uuid.UUID, matterID *uuid.UUID) ([]model.Document, error) {
	query := `
		SELECT d.document_id, d.firm_id, d.matter_id, d.title, d.filename, d.document_type, d.tags,
		       d.created_by, d.created_at, d.updated_at, d.deleted_at,
		       COALESCE(u.display_name, ''),
		       COALESCE(m.title, ''),
		       COALESCE(v.file_size, 0), COALESCE(v.mime_type, ''),
		       (SELECT count(*) FROM document_versions dv WHERE dv.document_id = d.document_id)
		FROM documents d
		LEFT JOIN users u ON u.user_id = d.created_by
		LEFT JOIN matters m ON m.matter_id = d.matter_id
		LEFT JOIN document_versions v ON v.document_id = d.document_id AND v.is_current = true
		WHERE d.firm_id = $1 AND d.deleted_at IS NULL
	`
	args := []any{firmID}
	if matterID != nil {
		query += " AND d.matter_id = $2"
		args = append(args, *matterID)
	}
	query += " ORDER BY d.updated_at DESC"

	rows, err := r.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var docs []model.Document
	for rows.Next() {
		var d model.Document
		if err := rows.Scan(
			&d.DocumentID, &d.FirmID, &d.MatterID, &d.Title, &d.Filename, &d.DocumentType, &d.Tags,
			&d.CreatedBy, &d.CreatedAt, &d.UpdatedAt, &d.DeletedAt,
			&d.CreatorName, &d.MatterTitle, &d.CurrentSize, &d.CurrentMime, &d.VersionCount,
		); err != nil {
			return nil, err
		}
		docs = append(docs, d)
	}
	return docs, nil
}

// --- Conversations ---

func (r *Repository) CreateConversation(ctx context.Context, c *model.Conversation) error {
	return r.pool.QueryRow(ctx, `
		INSERT INTO conversations (firm_id, user_id, matter_id, title, model_id)
		VALUES ($1, $2, $3, $4, $5)
		RETURNING conversation_id, created_at, updated_at
	`, c.FirmID, c.UserID, c.MatterID, c.Title, c.ModelID,
	).Scan(&c.ConversationID, &c.CreatedAt, &c.UpdatedAt)
}

func (r *Repository) ListConversations(ctx context.Context, firmID, userID uuid.UUID) ([]model.Conversation, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT c.conversation_id, c.firm_id, c.user_id, c.matter_id, c.title, c.model_id,
		       c.created_at, c.updated_at,
		       (SELECT count(*) FROM messages msg WHERE msg.conversation_id = c.conversation_id),
		       COALESCE(m.title, '')
		FROM conversations c
		LEFT JOIN matters m ON m.matter_id = c.matter_id
		WHERE c.firm_id = $1 AND c.user_id = $2 AND c.deleted_at IS NULL
		ORDER BY c.updated_at DESC
	`, firmID, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var convs []model.Conversation
	for rows.Next() {
		var c model.Conversation
		if err := rows.Scan(
			&c.ConversationID, &c.FirmID, &c.UserID, &c.MatterID, &c.Title, &c.ModelID,
			&c.CreatedAt, &c.UpdatedAt, &c.MessageCount, &c.MatterTitle,
		); err != nil {
			return nil, err
		}
		convs = append(convs, c)
	}
	return convs, nil
}

func (r *Repository) CreateMessage(ctx context.Context, m *model.Message) error {
	return r.pool.QueryRow(ctx, `
		INSERT INTO messages (conversation_id, role, content, model_used, tokens_input, tokens_output, latency_ms, abstained)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		RETURNING message_id, created_at
	`, m.ConversationID, m.Role, m.Content, m.ModelUsed, m.TokensInput, m.TokensOutput, m.LatencyMs, m.Abstained,
	).Scan(&m.MessageID, &m.CreatedAt)
}

func (r *Repository) ListMessages(ctx context.Context, conversationID uuid.UUID) ([]model.Message, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT message_id, conversation_id, role, content, model_used, tokens_input, tokens_output, latency_ms, abstained, created_at
		FROM messages WHERE conversation_id = $1
		ORDER BY created_at ASC
	`, conversationID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var msgs []model.Message
	for rows.Next() {
		var m model.Message
		if err := rows.Scan(&m.MessageID, &m.ConversationID, &m.Role, &m.Content, &m.ModelUsed, &m.TokensInput, &m.TokensOutput, &m.LatencyMs, &m.Abstained, &m.CreatedAt); err != nil {
			return nil, err
		}
		msgs = append(msgs, m)
	}
	return msgs, nil
}
