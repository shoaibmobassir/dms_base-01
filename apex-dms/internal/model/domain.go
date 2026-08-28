package model

import (
	"time"

	"github.com/google/uuid"
)

// Client represents a firm's client (individual or organisation).
type Client struct {
	ClientID     uuid.UUID  `json:"client_id"`
	FirmID       uuid.UUID  `json:"firm_id"`
	Name         string     `json:"name"`
	ClientType   string     `json:"client_type"`
	ContactEmail *string    `json:"contact_email,omitempty"`
	ContactPhone *string    `json:"contact_phone,omitempty"`
	Notes        *string    `json:"notes,omitempty"`
	CreatedAt    time.Time  `json:"created_at"`
	UpdatedAt    time.Time  `json:"updated_at"`
}

// PracticeArea represents a firm's practice area.
type PracticeArea struct {
	AreaID    uuid.UUID `json:"area_id"`
	FirmID    uuid.UUID `json:"firm_id"`
	Name      string    `json:"name"`
	Color     string    `json:"color"`
	SortOrder int       `json:"sort_order"`
}

// MatterStatus represents valid matter statuses.
type MatterStatus string

const (
	MatterStatusDraft    MatterStatus = "draft"
	MatterStatusActive   MatterStatus = "active"
	MatterStatusOnHold   MatterStatus = "on_hold"
	MatterStatusClosed   MatterStatus = "closed"
	MatterStatusArchived MatterStatus = "archived"
)

// Matter represents a legal matter/case/project.
type Matter struct {
	MatterID       uuid.UUID    `json:"matter_id"`
	FirmID         uuid.UUID    `json:"firm_id"`
	MatterCode     string       `json:"matter_code"`
	Title          string       `json:"title"`
	Description    *string      `json:"description,omitempty"`
	PracticeAreaID *uuid.UUID   `json:"practice_area_id,omitempty"`
	ClientID       *uuid.UUID   `json:"client_id,omitempty"`
	Status         MatterStatus `json:"status"`
	LeadUserID     *uuid.UUID   `json:"lead_user_id,omitempty"`
	Metadata       any          `json:"metadata,omitempty"`
	CreatedAt      time.Time    `json:"created_at"`
	UpdatedAt      time.Time    `json:"updated_at"`
	ClosedAt       *time.Time   `json:"closed_at,omitempty"`
	DeletedAt      *time.Time   `json:"deleted_at,omitempty"`

	// Joined fields
	ClientName       string `json:"client_name,omitempty"`
	PracticeAreaName string `json:"practice_area_name,omitempty"`
	LeadName         string `json:"lead_name,omitempty"`
	DocumentCount    int    `json:"document_count"`
	MemberCount      int    `json:"member_count"`
}

// MatterMember represents a user's role within a matter.
type MatterMember struct {
	MatterID   uuid.UUID `json:"matter_id"`
	UserID     uuid.UUID `json:"user_id"`
	MatterRole string    `json:"matter_role"`
	AssignedAt time.Time `json:"assigned_at"`
	// Joined
	DisplayName string  `json:"display_name,omitempty"`
	Email       string  `json:"email,omitempty"`
	AvatarURL   *string `json:"avatar_url,omitempty"`
}

// Document represents an uploaded document.
type Document struct {
	DocumentID   uuid.UUID  `json:"document_id"`
	FirmID       uuid.UUID  `json:"firm_id"`
	MatterID     *uuid.UUID `json:"matter_id,omitempty"`
	Title        string     `json:"title"`
	Filename     string     `json:"filename"`
	DocumentType *string    `json:"document_type,omitempty"`
	Tags         []string   `json:"tags"`
	CreatedBy    uuid.UUID  `json:"created_by"`
	CreatedAt    time.Time  `json:"created_at"`
	UpdatedAt    time.Time  `json:"updated_at"`
	DeletedAt    *time.Time `json:"deleted_at,omitempty"`

	// Joined
	CreatorName   string `json:"creator_name,omitempty"`
	MatterTitle   string `json:"matter_title,omitempty"`
	CurrentSize   int64  `json:"current_size,omitempty"`
	CurrentMime   string `json:"current_mime,omitempty"`
	VersionCount  int    `json:"version_count"`
}

// DocumentVersion represents a specific version of a document.
type DocumentVersion struct {
	VersionID        uuid.UUID `json:"version_id"`
	DocumentID       uuid.UUID `json:"document_id"`
	VersionNumber    int       `json:"version_number"`
	StorageKey       string    `json:"storage_key"`
	FileSize         int64     `json:"file_size"`
	MimeType         string    `json:"mime_type"`
	PageCount        *int      `json:"page_count,omitempty"`
	ContentHash      string    `json:"content_hash"`
	UploadedBy       uuid.UUID `json:"uploaded_by"`
	UploadedAt       time.Time `json:"uploaded_at"`
	IsCurrent        bool      `json:"is_current"`
	ProcessingStatus string    `json:"processing_status"`
}

// Conversation represents an AI chat conversation.
type Conversation struct {
	ConversationID uuid.UUID  `json:"conversation_id"`
	FirmID         uuid.UUID  `json:"firm_id"`
	UserID         uuid.UUID  `json:"user_id"`
	MatterID       *uuid.UUID `json:"matter_id,omitempty"`
	Title          *string    `json:"title,omitempty"`
	ModelID        string     `json:"model_id"`
	CreatedAt      time.Time  `json:"created_at"`
	UpdatedAt      time.Time  `json:"updated_at"`

	// Joined
	MessageCount int    `json:"message_count"`
	MatterTitle  string `json:"matter_title,omitempty"`
}

// Message represents a single chat message.
type Message struct {
	MessageID      uuid.UUID `json:"message_id"`
	ConversationID uuid.UUID `json:"conversation_id"`
	Role           string    `json:"role"`
	Content        string    `json:"content"`
	ModelUsed      *string   `json:"model_used,omitempty"`
	TokensInput    *int      `json:"tokens_input,omitempty"`
	TokensOutput   *int      `json:"tokens_output,omitempty"`
	LatencyMs      *int      `json:"latency_ms,omitempty"`
	Abstained      bool      `json:"abstained"`
	CreatedAt      time.Time `json:"created_at"`
}
