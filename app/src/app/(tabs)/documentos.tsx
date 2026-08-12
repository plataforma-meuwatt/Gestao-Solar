import { Text } from 'react-native'

import { Card } from '@/components/base'
import { Tela } from '@/components/Tela'
import { usuario } from '@/features/exemplo'
import { tipo } from '@/theme/tokens'

export default function Documentos() {
  return (
    <Tela titulo="Documentos" avatar={{ iniciais: usuario.iniciais }} paraTabBar>
      <Card>
        <Text style={tipo.corpo}>
          Relatórios, ordens de serviço e cronograma em PDF entram na Fase 5, quando o BFF
          ganhar o render headless que roda o motor vetorial do mw-fe.
        </Text>
      </Card>
    </Tela>
  )
}
