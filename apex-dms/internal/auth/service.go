package auth

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/apex-chambers/dms/internal/config"
	"github.com/apex-chambers/dms/internal/model"
	"github.com/google/uuid"
	"golang.org/x/crypto/argon2"
)

// Argon2id parameters
const (
	argonTime    = 1
	argonMemory  = 64 * 1024 // 64 MB
	argonThreads = 4
	argonKeyLen  = 32
	argonSaltLen = 16
)

var slugRe = regexp.MustCompile(`[^a-z0-9]+`)

// Service handles authentication business logic.
type Service struct {
	repo *Repository
	jwt  *JWTManager
	cfg  *config.Config
}

// NewService creates a new auth service.
func NewService(repo *Repository, jwtMgr *JWTManager, cfg *config.Config) *Service {
	return &Service{repo: repo, jwt: jwtMgr, cfg: cfg}
}

// RegisterRequest holds registration inputs.
type RegisterRequest struct {
	Email       string `json:"email"`
	Password    string `json:"password"`
	DisplayName string `json:"display_name"`
	FirmName    string `json:"firm_name"`
}

// RegisterResult holds registration outputs.
type RegisterResult struct {
	User         *model.User `json:"user"`
	Firm         *model.Firm `json:"firm"`
	AccessToken  string      `json:"access_token"`
	RefreshToken string      `json:"refresh_token"`
}

// Register creates a new user, a new firm, and makes the user the owner.
func (s *Service) Register(ctx context.Context, req RegisterRequest) (*RegisterResult, error) {
	// Validate
	if req.Email == "" || req.Password == "" || req.DisplayName == "" || req.FirmName == "" {
		return nil, fmt.Errorf("all fields are required")
	}
	if len(req.Password) < 8 {
		return nil, fmt.Errorf("password must be at least 8 characters")
	}

	// Check if email already exists
	existing, err := s.repo.FindUserByEmail(ctx, strings.ToLower(req.Email))
	if err != nil {
		return nil, fmt.Errorf("check existing: %w", err)
	}
	if existing != nil {
		return nil, fmt.Errorf("email already registered")
	}

	// Hash password
	hash, err := hashPassword(req.Password)
	if err != nil {
		return nil, fmt.Errorf("hash password: %w", err)
	}

	// Create user
	user, err := s.repo.CreateUser(ctx, strings.ToLower(req.Email), hash, req.DisplayName)
	if err != nil {
		return nil, fmt.Errorf("create user: %w", err)
	}

	// Create firm with slug
	slug := generateSlug(req.FirmName)
	firm, err := s.repo.CreateFirm(ctx, req.FirmName, slug)
	if err != nil {
		return nil, fmt.Errorf("create firm: %w", err)
	}

	// Make user the owner
	if err := s.repo.AddMember(ctx, firm.FirmID, user.UserID, model.RoleOwner); err != nil {
		return nil, fmt.Errorf("add owner: %w", err)
	}

	// Generate tokens
	accessToken, err := s.jwt.GenerateAccessToken(user.UserID, firm.FirmID, string(model.RoleOwner))
	if err != nil {
		return nil, fmt.Errorf("generate access token: %w", err)
	}

	plainRefresh, hashRefresh, err := GenerateRefreshToken()
	if err != nil {
		return nil, fmt.Errorf("generate refresh token: %w", err)
	}

	_, err = s.repo.StoreRefreshToken(ctx, user.UserID, hashRefresh,
		time.Now().Add(s.jwt.RefreshExpiration()))
	if err != nil {
		return nil, fmt.Errorf("store refresh token: %w", err)
	}

	return &RegisterResult{
		User:         user,
		Firm:         firm,
		AccessToken:  accessToken,
		RefreshToken: plainRefresh,
	}, nil
}

// LoginRequest holds login inputs.
type LoginRequest struct {
	Email    string    `json:"email"`
	Password string    `json:"password"`
	FirmID   uuid.UUID `json:"firm_id"` // which firm to log into (optional — uses first if empty)
}

// LoginResult holds login outputs.
type LoginResult struct {
	User         *model.User       `json:"user"`
	Membership   *model.FirmMember `json:"membership"`
	AccessToken  string            `json:"access_token"`
	RefreshToken string            `json:"refresh_token"`
}

// Login authenticates a user and returns tokens.
func (s *Service) Login(ctx context.Context, req LoginRequest) (*LoginResult, error) {
	user, err := s.repo.FindUserByEmail(ctx, strings.ToLower(req.Email))
	if err != nil {
		return nil, fmt.Errorf("find user: %w", err)
	}
	if user == nil {
		return nil, fmt.Errorf("invalid credentials")
	}

	if !verifyPassword(req.Password, user.PasswordHash) {
		return nil, fmt.Errorf("invalid credentials")
	}

	// Determine which firm to log into
	firmID := req.FirmID
	if firmID == uuid.Nil {
		// Use the first firm the user belongs to
		firms, err := s.repo.GetUserFirms(ctx, user.UserID)
		if err != nil || len(firms) == 0 {
			return nil, fmt.Errorf("user has no firm membership")
		}
		firmID = firms[0].FirmID
	}

	membership, err := s.repo.GetMembership(ctx, firmID, user.UserID)
	if err != nil {
		return nil, fmt.Errorf("get membership: %w", err)
	}
	if membership == nil {
		return nil, fmt.Errorf("not a member of this firm")
	}

	// Generate tokens
	accessToken, err := s.jwt.GenerateAccessToken(user.UserID, firmID, string(membership.Role))
	if err != nil {
		return nil, fmt.Errorf("generate access token: %w", err)
	}

	plainRefresh, hashRefresh, err := GenerateRefreshToken()
	if err != nil {
		return nil, fmt.Errorf("generate refresh token: %w", err)
	}

	_, err = s.repo.StoreRefreshToken(ctx, user.UserID, hashRefresh,
		time.Now().Add(s.jwt.RefreshExpiration()))
	if err != nil {
		return nil, fmt.Errorf("store refresh token: %w", err)
	}

	return &LoginResult{
		User:         user,
		Membership:   membership,
		AccessToken:  accessToken,
		RefreshToken: plainRefresh,
	}, nil
}

// Refresh validates a refresh token and issues new tokens.
func (s *Service) Refresh(ctx context.Context, refreshTokenPlain string) (*LoginResult, error) {
	hash := HashToken(refreshTokenPlain)
	rt, err := s.repo.FindRefreshToken(ctx, hash)
	if err != nil {
		return nil, fmt.Errorf("find refresh token: %w", err)
	}
	if rt == nil || rt.RevokedAt != nil {
		return nil, fmt.Errorf("invalid refresh token")
	}
	if time.Now().After(rt.ExpiresAt) {
		return nil, fmt.Errorf("refresh token expired")
	}

	// Revoke old token (rotation)
	if err := s.repo.RevokeRefreshToken(ctx, rt.TokenID); err != nil {
		return nil, fmt.Errorf("revoke old token: %w", err)
	}

	user, err := s.repo.FindUserByID(ctx, rt.UserID)
	if err != nil || user == nil {
		return nil, fmt.Errorf("user not found")
	}

	// Get first firm membership for new token
	firms, err := s.repo.GetUserFirms(ctx, user.UserID)
	if err != nil || len(firms) == 0 {
		return nil, fmt.Errorf("no firm membership")
	}

	membership, err := s.repo.GetMembership(ctx, firms[0].FirmID, user.UserID)
	if err != nil || membership == nil {
		return nil, fmt.Errorf("membership not found")
	}

	accessToken, err := s.jwt.GenerateAccessToken(user.UserID, firms[0].FirmID, string(membership.Role))
	if err != nil {
		return nil, fmt.Errorf("generate access token: %w", err)
	}

	newPlain, newHash, err := GenerateRefreshToken()
	if err != nil {
		return nil, fmt.Errorf("generate new refresh token: %w", err)
	}

	_, err = s.repo.StoreRefreshToken(ctx, user.UserID, newHash,
		time.Now().Add(s.jwt.RefreshExpiration()))
	if err != nil {
		return nil, fmt.Errorf("store new refresh token: %w", err)
	}

	return &LoginResult{
		User:         user,
		Membership:   membership,
		AccessToken:  accessToken,
		RefreshToken: newPlain,
	}, nil
}

// Logout revokes all refresh tokens for a user.
func (s *Service) Logout(ctx context.Context, userID uuid.UUID) error {
	return s.repo.RevokeAllUserTokens(ctx, userID)
}

// --- Password hashing (Argon2id) ---

func hashPassword(password string) (string, error) {
	salt := make([]byte, argonSaltLen)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}

	hash := argon2.IDKey([]byte(password), salt, argonTime, argonMemory, argonThreads, argonKeyLen)

	b64Salt := base64.RawStdEncoding.EncodeToString(salt)
	b64Hash := base64.RawStdEncoding.EncodeToString(hash)

	return fmt.Sprintf("$argon2id$v=%d$m=%d,t=%d,p=%d$%s$%s",
		argon2.Version, argonMemory, argonTime, argonThreads, b64Salt, b64Hash), nil
}

func verifyPassword(password, encodedHash string) bool {
	// Parse the encoded hash
	var version int
	var memory uint32
	var iterations uint32
	var parallelism uint8
	var salt, hash string

	_, err := fmt.Sscanf(encodedHash, "$argon2id$v=%d$m=%d,t=%d,p=%d$%s",
		&version, &memory, &iterations, &parallelism, &salt)
	if err != nil {
		return false
	}

	// Split salt$hash
	parts := strings.Split(salt, "$")
	if len(parts) != 2 {
		return false
	}
	salt = parts[0]
	hash = parts[1]

	saltBytes, err := base64.RawStdEncoding.DecodeString(salt)
	if err != nil {
		return false
	}

	hashBytes, err := base64.RawStdEncoding.DecodeString(hash)
	if err != nil {
		return false
	}

	computed := argon2.IDKey([]byte(password), saltBytes, iterations, memory, parallelism, uint32(len(hashBytes)))
	return subtle.ConstantTimeCompare(computed, hashBytes) == 1
}

func generateSlug(name string) string {
	slug := strings.ToLower(name)
	slug = slugRe.ReplaceAllString(slug, "-")
	slug = strings.Trim(slug, "-")
	if slug == "" {
		slug = "firm"
	}
	// Append short random suffix for uniqueness
	b := make([]byte, 4)
	rand.Read(b)
	return fmt.Sprintf("%s-%s", slug, hex.EncodeToString(b))
}
