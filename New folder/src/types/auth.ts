export type UserRole = 'developer' | 'lead' | 'admin'

export interface User {
  id: string
  email: string
  full_name: string | null
  role: UserRole
  created_at: string
}

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

export interface RegisterInput {
  email: string
  password: string
  full_name?: string
}
