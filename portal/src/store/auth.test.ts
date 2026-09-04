/**
 * O que este teste guarda é uma regra de segurança, não de conveniência.
 *
 * O caso real está no aplicativo e vale igual no navegador: a mesma pessoa tem conta de
 * gestor e conta de dono, e usa as duas no mesmo computador. Se `sair()` deixar para trás o
 * token, a chave de sessão ou uma linha de `leitura:*`, as usinas de quem saiu aparecem para
 * quem entra — apresentadas como leitura ao vivo. Isso é vazamento, não atraso.
 *
 * Também está aqui a separação de portais: a chave é `gs_portal_sessao`, e não a
 * `gs_painel_sessao` do painel do gestor. As duas convivem no mesmo navegador.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { gravarCache, identificarCache } from '@/lib/leitura'
import { useAuth, type Usuario } from '@/store/auth'

const CHAVE = 'gs_portal_sessao'

const usuario: Usuario = {
  id: 7,
  nome: 'Cliente de Teste',
  apelido: 'cliente',
  email: null,
  empresa: 'Usina Boa',
  tem_meuwatt: true,
  tem_meuplano: true,
  nivel_acesso: 1,
  usinas: 2,
  trocar_senha: false,
}

describe('sessão do portal', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuth.setState({ token: null, expiraEm: null, usuario: null, erro: null, entrando: false })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('entra pela porta do cliente e guarda a sessão na chave do portal', async () => {
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: { token: 'tok', expira_em: '2026-12-01T00:00:00Z', usuario } })

    const ok = await useAuth.getState().entrar('  cliente ', 'senha')

    expect(ok).toBe(true)
    expect(post).toHaveBeenCalledWith('/api/v1/auth/login', { apelido: 'cliente', senha: 'senha' })
    expect(useAuth.getState().token).toBe('tok')
    expect(localStorage.getItem(CHAVE)).toContain('tok')
    // A chave do painel não é tocada: os dois sites podem estar abertos lado a lado.
    expect(localStorage.getItem('gs_painel_sessao')).toBeNull()
  })

  it('erro de login vira frase, e não sessão pela metade', async () => {
    vi.spyOn(api, 'post').mockRejectedValue(new Error('Apelido ou senha inválidos.'))

    const ok = await useAuth.getState().entrar('cliente', 'errada')

    expect(ok).toBe(false)
    expect(useAuth.getState().token).toBeNull()
    expect(useAuth.getState().erro).toBe('Apelido ou senha inválidos.')
  })

  it('sair não deixa sessão nem cache de leitura para trás', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'tok', usuario } })
    await useAuth.getState().entrar('cliente', 'senha')
    identificarCache(usuario.id)
    gravarCache('resumo', { usinas: 2 })
    expect(Object.keys(localStorage).some((k) => k.startsWith('leitura:'))).toBe(true)

    useAuth.getState().sair()

    expect(useAuth.getState().token).toBeNull()
    expect(useAuth.getState().usuario).toBeNull()
    expect(localStorage.getItem(CHAVE)).toBeNull()
    expect(Object.keys(localStorage).some((k) => k.startsWith('leitura:'))).toBe(false)
  })

  it('só renova quando falta menos de uma semana', async () => {
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'novo', usuario } })

    const longe = new Date(Date.now() + 25 * 24 * 60 * 60 * 1000).toISOString()
    useAuth.setState({ token: 'tok', expiraEm: longe, usuario })
    await useAuth.getState().renovar()
    expect(post).not.toHaveBeenCalled()

    const perto = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString()
    useAuth.setState({ token: 'tok', expiraEm: perto, usuario })
    await useAuth.getState().renovar()
    expect(post).toHaveBeenCalledWith('/api/v1/auth/renovar')
    expect(useAuth.getState().token).toBe('novo')
  })

  it('hidratar revalida o perfil no servidor (a senha provisória que o gestor marcou)', async () => {
    useAuth.setState({ token: 'tok', expiraEm: null, usuario })
    vi.spyOn(api, 'get').mockResolvedValue({ data: { ...usuario, trocar_senha: true } })

    await useAuth.getState().hidratar()

    expect(useAuth.getState().usuario?.trocar_senha).toBe(true)
    expect(localStorage.getItem(CHAVE)).toContain('"trocar_senha":true')
  })

  it('sem token, hidratar e renovar não chamam o servidor', async () => {
    const get = vi.spyOn(api, 'get')
    const post = vi.spyOn(api, 'post')

    await useAuth.getState().hidratar()
    await useAuth.getState().renovar()

    expect(get).not.toHaveBeenCalled()
    expect(post).not.toHaveBeenCalled()
  })
})
