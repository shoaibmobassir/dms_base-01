package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/apex-chambers/dms/internal/config"
	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
)

// Claims represents the JWT payload.
type Claims struct {
	UserID uuid.UUID `json:"user_id"`
	FirmID uuid.UUID `json:"firm_id"`
	Role   string    `json:"role"`
	jwt.RegisteredClaims
}

// JWTManager handles JWT creation and validation.
type JWTManager struct {
	secretKey         []byte
	accessExpiration  time.Duration
	refreshExpiration time.Duration
}

// NewJWTManager creates a new JWT manager.
func NewJWTManager(cfg *config.Config) *JWTManager {
	return &JWTManager{
		secretKey:         []byte(cfg.JWTSecretKey),
		accessExpiration:  cfg.JWTAccessTokenExpiration,
		refreshExpiration: cfg.JWTRefreshTokenExpiration,
	}
}

// GenerateAccessToken creates a short-lived access JWT.
func (m *JWTManager) GenerateAccessToken(userID, firmID uuid.UUID, role string) (string, error) {
	now := time.Now()
	claims := Claims{
		UserID: userID,
		FirmID: firmID,
		Role:   role,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(now.Add(m.accessExpiration)),
			IssuedAt:  jwt.NewNumericDate(now),
			NotBefore: jwt.NewNumericDate(now),
			Issuer:    "apex-dms",
			Subject:   userID.String(),
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(m.secretKey)
}

// ValidateToken parses and validates a JWT, returning user_id, firm_id, role.
// This satisfies the middleware.TokenValidator interface.
func (m *JWTManager) ValidateToken(tokenString string) (uuid.UUID, uuid.UUID, string, error) {
	claims, err := m.parseToken(tokenString)
	if err != nil {
		return uuid.Nil, uuid.Nil, "", err
	}
	return claims.UserID, claims.FirmID, claims.Role, nil
}

// parseToken parses and validates a JWT, returning its claims (internal use).
func (m *JWTManager) parseToken(tokenString string) (*Claims, error) {
	token, err := jwt.ParseWithClaims(tokenString, &Claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return m.secretKey, nil
	})
	if err != nil {
		return nil, fmt.Errorf("parse token: %w", err)
	}

	claims, ok := token.Claims.(*Claims)
	if !ok || !token.Valid {
		return nil, fmt.Errorf("invalid token claims")
	}
	return claims, nil
}

// GenerateRefreshToken creates a cryptographically random refresh token string.
func GenerateRefreshToken() (plaintext string, hash string, err error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", "", fmt.Errorf("generate random bytes: %w", err)
	}
	plaintext = hex.EncodeToString(b)
	hash = HashToken(plaintext)
	return plaintext, hash, nil
}

// HashToken creates a SHA-256 hash of a token for storage.
func HashToken(token string) string {
	h := sha256.Sum256([]byte(token))
	return hex.EncodeToString(h[:])
}

// RefreshExpiration returns how long refresh tokens last.
func (m *JWTManager) RefreshExpiration() time.Duration {
	return m.refreshExpiration
}
