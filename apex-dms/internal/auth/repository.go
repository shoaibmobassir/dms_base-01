package auth

import (
	"context"
	"fmt"
	"time"

	"github.com/apex-chambers/dms/internal/model"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Repository handles database operations for auth entities.
type Repository struct {
	pool *pgxpool.Pool
}

// NewRepository creates a new auth repository.
func NewRepository(pool *pgxpool.Pool) *Repository {
	return &Repository{pool: pool}
}

// --- Users ---

// CreateUser inserts a new user and returns it.
func (r *Repository) CreateUser(ctx context.Context, email, passwordHash, displayName string) (*model.User, error) {
	u := &model.User{}
	err := r.pool.QueryRow(ctx, `
		INSERT INTO users (email, password_hash, display_name)
		VALUES ($1, $2, $3)
		RETURNING user_id, email, password_hash, display_name, avatar_url,
		          email_verified, created_at, updated_at
	`, email, passwordHash, displayName).Scan(
		&u.UserID, &u.Email, &u.PasswordHash, &u.DisplayName, &u.AvatarURL,
		&u.EmailVerified, &u.CreatedAt, &u.UpdatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("create user: %w", err)
	}
	return u, nil
}

// FindUserByEmail returns a user by email address.
func (r *Repository) FindUserByEmail(ctx context.Context, email string) (*model.User, error) {
	u := &model.User{}
	err := r.pool.QueryRow(ctx, `
		SELECT user_id, email, password_hash, display_name, avatar_url,
		       email_verified, mfa_secret, created_at, updated_at
		FROM users WHERE email = $1
	`, email).Scan(
		&u.UserID, &u.Email, &u.PasswordHash, &u.DisplayName, &u.AvatarURL,
		&u.EmailVerified, &u.MFASecret, &u.CreatedAt, &u.UpdatedAt,
	)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("find user by email: %w", err)
	}
	return u, nil
}

// FindUserByID returns a user by ID.
func (r *Repository) FindUserByID(ctx context.Context, id uuid.UUID) (*model.User, error) {
	u := &model.User{}
	err := r.pool.QueryRow(ctx, `
		SELECT user_id, email, password_hash, display_name, avatar_url,
		       email_verified, created_at, updated_at
		FROM users WHERE user_id = $1
	`, id).Scan(
		&u.UserID, &u.Email, &u.PasswordHash, &u.DisplayName, &u.AvatarURL,
		&u.EmailVerified, &u.CreatedAt, &u.UpdatedAt,
	)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("find user by id: %w", err)
	}
	return u, nil
}

// UpdateUser updates user profile fields.
func (r *Repository) UpdateUser(ctx context.Context, id uuid.UUID, displayName string, avatarURL *string) error {
	_, err := r.pool.Exec(ctx, `
		UPDATE users SET display_name = $2, avatar_url = $3, updated_at = now()
		WHERE user_id = $1
	`, id, displayName, avatarURL)
	return err
}

// --- Firms ---

// CreateFirm inserts a new firm.
func (r *Repository) CreateFirm(ctx context.Context, name, slug string) (*model.Firm, error) {
	f := &model.Firm{}
	err := r.pool.QueryRow(ctx, `
		INSERT INTO firms (name, slug) VALUES ($1, $2)
		RETURNING firm_id, name, slug, logo_url, address, settings, created_at, updated_at
	`, name, slug).Scan(
		&f.FirmID, &f.Name, &f.Slug, &f.LogoURL, &f.Address,
		&f.Settings, &f.CreatedAt, &f.UpdatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("create firm: %w", err)
	}
	return f, nil
}

// FindFirmByID returns a firm by ID.
func (r *Repository) FindFirmByID(ctx context.Context, id uuid.UUID) (*model.Firm, error) {
	f := &model.Firm{}
	err := r.pool.QueryRow(ctx, `
		SELECT firm_id, name, slug, logo_url, address, settings, created_at, updated_at
		FROM firms WHERE firm_id = $1
	`, id).Scan(
		&f.FirmID, &f.Name, &f.Slug, &f.LogoURL, &f.Address,
		&f.Settings, &f.CreatedAt, &f.UpdatedAt,
	)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("find firm by id: %w", err)
	}
	return f, nil
}

// --- Firm Members ---

// AddMember adds a user to a firm with the given role.
func (r *Repository) AddMember(ctx context.Context, firmID, userID uuid.UUID, role model.Role) error {
	_, err := r.pool.Exec(ctx, `
		INSERT INTO firm_members (firm_id, user_id, role)
		VALUES ($1, $2, $3)
		ON CONFLICT (firm_id, user_id) DO UPDATE SET role = $3
	`, firmID, userID, string(role))
	return err
}

// GetMembership returns a user's membership in a firm.
func (r *Repository) GetMembership(ctx context.Context, firmID, userID uuid.UUID) (*model.FirmMember, error) {
	m := &model.FirmMember{}
	err := r.pool.QueryRow(ctx, `
		SELECT fm.firm_id, fm.user_id, fm.role, fm.joined_at,
		       u.display_name, u.email, u.avatar_url
		FROM firm_members fm
		JOIN users u ON u.user_id = fm.user_id
		WHERE fm.firm_id = $1 AND fm.user_id = $2
	`, firmID, userID).Scan(
		&m.FirmID, &m.UserID, &m.Role, &m.JoinedAt,
		&m.DisplayName, &m.Email, &m.AvatarURL,
	)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("get membership: %w", err)
	}
	return m, nil
}

// ListMembers returns all members of a firm.
func (r *Repository) ListMembers(ctx context.Context, firmID uuid.UUID) ([]model.FirmMember, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT fm.firm_id, fm.user_id, fm.role, fm.joined_at,
		       u.display_name, u.email, u.avatar_url
		FROM firm_members fm
		JOIN users u ON u.user_id = fm.user_id
		WHERE fm.firm_id = $1
		ORDER BY fm.joined_at ASC
	`, firmID)
	if err != nil {
		return nil, fmt.Errorf("list members: %w", err)
	}
	defer rows.Close()

	var members []model.FirmMember
	for rows.Next() {
		var m model.FirmMember
		if err := rows.Scan(
			&m.FirmID, &m.UserID, &m.Role, &m.JoinedAt,
			&m.DisplayName, &m.Email, &m.AvatarURL,
		); err != nil {
			return nil, fmt.Errorf("scan member: %w", err)
		}
		members = append(members, m)
	}
	return members, nil
}

// GetUserFirms returns all firms a user belongs to.
func (r *Repository) GetUserFirms(ctx context.Context, userID uuid.UUID) ([]model.FirmMember, error) {
	rows, err := r.pool.Query(ctx, `
		SELECT fm.firm_id, fm.user_id, fm.role, fm.joined_at
		FROM firm_members fm
		WHERE fm.user_id = $1
		ORDER BY fm.joined_at ASC
	`, userID)
	if err != nil {
		return nil, fmt.Errorf("get user firms: %w", err)
	}
	defer rows.Close()

	var memberships []model.FirmMember
	for rows.Next() {
		var m model.FirmMember
		if err := rows.Scan(&m.FirmID, &m.UserID, &m.Role, &m.JoinedAt); err != nil {
			return nil, fmt.Errorf("scan membership: %w", err)
		}
		memberships = append(memberships, m)
	}
	return memberships, nil
}

// --- Refresh Tokens ---

// StoreRefreshToken saves a hashed refresh token.
func (r *Repository) StoreRefreshToken(ctx context.Context, userID uuid.UUID, tokenHash string, expiresAt time.Time) (*model.RefreshToken, error) {
	rt := &model.RefreshToken{}
	err := r.pool.QueryRow(ctx, `
		INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
		VALUES ($1, $2, $3)
		RETURNING token_id, user_id, token_hash, expires_at, created_at
	`, userID, tokenHash, expiresAt).Scan(
		&rt.TokenID, &rt.UserID, &rt.TokenHash, &rt.ExpiresAt, &rt.CreatedAt,
	)
	if err != nil {
		return nil, fmt.Errorf("store refresh token: %w", err)
	}
	return rt, nil
}

// FindRefreshToken finds a refresh token by its hash.
func (r *Repository) FindRefreshToken(ctx context.Context, tokenHash string) (*model.RefreshToken, error) {
	rt := &model.RefreshToken{}
	err := r.pool.QueryRow(ctx, `
		SELECT token_id, user_id, token_hash, expires_at, revoked_at, created_at
		FROM refresh_tokens
		WHERE token_hash = $1
	`, tokenHash).Scan(
		&rt.TokenID, &rt.UserID, &rt.TokenHash, &rt.ExpiresAt, &rt.RevokedAt, &rt.CreatedAt,
	)
	if err != nil {
		if err == pgx.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("find refresh token: %w", err)
	}
	return rt, nil
}

// RevokeRefreshToken marks a refresh token as revoked.
func (r *Repository) RevokeRefreshToken(ctx context.Context, tokenID uuid.UUID) error {
	_, err := r.pool.Exec(ctx, `
		UPDATE refresh_tokens SET revoked_at = now() WHERE token_id = $1
	`, tokenID)
	return err
}

// RevokeAllUserTokens revokes all refresh tokens for a user.
func (r *Repository) RevokeAllUserTokens(ctx context.Context, userID uuid.UUID) error {
	_, err := r.pool.Exec(ctx, `
		UPDATE refresh_tokens SET revoked_at = now()
		WHERE user_id = $1 AND revoked_at IS NULL
	`, userID)
	return err
}
