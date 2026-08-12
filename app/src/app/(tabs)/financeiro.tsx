import { Text } from 'react-native'

import { Card } from '@/components/base'
import { Tela } from '@/components/Tela'
import { usuario } from '@/features/exemplo'
import { tipo } from '@/theme/tokens'

export default function Financeiro() {
  return (
    <Tela titulo="Financeiro" avatar={{ iniciais: usuario.iniciais }} paraTabBar>
      <Card>
        <Text style={tipo.corpo}>
          As mensalidades do meuWatt e do meuPlano entram na Fase 6. O modelo já existe no
          BFF (gs_subscriptions e gs_invoices) — falta a tela e o cadastro.
        </Text>
      </Card>
    </Tela>
  )
}
