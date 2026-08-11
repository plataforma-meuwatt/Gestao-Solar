import { Text } from 'react-native'

import { Card } from '@/components/Card'
import { TelaColapsavel } from '@/components/TelaColapsavel'
import { tipo } from '@/theme/tokens'

export default function Documentos() {
  return (
    <TelaColapsavel titulo="Documentos">
      <Card>
        <Text style={tipo.corpo}>
          Relatórios, OS e cronograma em PDF entram na Fase 5.
        </Text>
      </Card>
    </TelaColapsavel>
  )
}
