import { Text } from 'react-native'

import { Card } from '@/components/base'
import { Tela } from '@/components/Tela'
import { usuario } from '@/features/exemplo'
import { tipo } from '@/theme/tokens'

export default function Assistente() {
  return (
    <Tela titulo="Assistente" avatar={{ iniciais: usuario.iniciais }} paraTabBar>
      <Card>
        <Text style={tipo.corpo}>
          O chat entra na Fase 7, sobre o assistente do meuPlano. A revelação de credencial
          depende de soltar o teto L1 do cliente lá — ver docs/ARQUITETURA.md.
        </Text>
      </Card>
    </Tela>
  )
}
