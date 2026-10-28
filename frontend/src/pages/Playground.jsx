import { useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Divider,
  Empty,
  Image,
  Input,
  InputNumber,
  Row,
  Slider,
  Space,
  Statistic,
  Switch,
  Tag,
  Typography,
} from 'antd'
import { DislikeOutlined, LikeOutlined, SendOutlined } from '@ant-design/icons'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { chat, figures as figuresApi } from '../api/endpoints'

const EXAMPLES = [
  'Какие ветви имеет наружная сонная артерия?',
  'Расскажи строение плечевой кости',
  'Какие мышцы относятся к передней группе мышц бедра?',
  'Что проходит через яремное отверстие?',
  'Чем отличается тощая кишка от подвздошной?',
]

export default function Playground() {
  const { message } = App.useApp()
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [useOverrides, setUseOverrides] = useState(false)
  const [overrides, setOverrides] = useState({
    temperature: 0.2,
    rerank_top_n: 5,
    min_relevance_score: 0.35,
  })

  const ask = async () => {
    if (question.trim().length < 3) {
      message.warning('Сформулируйте вопрос')
      return
    }

    setLoading(true)
    setResult(null)
    try {
      const { data } = await chat.ask({
        question,
        overrides: useOverrides ? overrides : null,
      })
      setResult(data)
    } finally {
      setLoading(false)
    }
  }

  const sendFeedback = async (value) => {
    await chat.feedback(result.message_id, value)
    message.success('Оценка сохранена')
  }

  return (
    <div>
      <div className="page-header">
        <h2>Проверка бота</h2>
        <div className="subtitle">
          Видно найденные фрагменты, их оценки и время работы
        </div>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card size="small">
            <Input.TextArea
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Задайте вопрос по анатомии"
              onPressEnter={(e) => {
                if (e.ctrlKey || e.metaKey) ask()
              }}
            />
            <div
              style={{
                marginTop: 12,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 12,
                flexWrap: 'wrap',
              }}
            >
              <Space wrap size={4}>
                {EXAMPLES.map((example) => (
                  <Tag
                    key={example}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setQuestion(example)}
                  >
                    {example}
                  </Tag>
                ))}
              </Space>
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={loading}
                onClick={ask}
              >
                Спросить
              </Button>
            </div>
          </Card>

          {result && (
            <Card
              size="small"
              style={{ marginTop: 16 }}
              title={
                result.refused ? (
                  <Tag color="orange">Отказ: нет данных в базе</Tag>
                ) : (
                  <Tag color="green">Ответ сформирован</Tag>
                )
              }
              extra={
                <Space>
                  <Button
                    size="small"
                    icon={<LikeOutlined />}
                    onClick={() => sendFeedback(1)}
                  />
                  <Button
                    size="small"
                    icon={<DislikeOutlined />}
                    onClick={() => sendFeedback(-1)}
                  />
                </Space>
              }
            >
              {result.error && (
                <Alert
                  type="error"
                  showIcon
                  message={result.error}
                  style={{ marginBottom: 12 }}
                />
              )}

              <div className="answer-body">
                <Markdown remarkPlugins={[remarkGfm]}>{result.answer}</Markdown>
              </div>

              {result.figures?.length > 0 && (
                <>
                  <Divider orientation="left" plain style={{ fontSize: 13 }}>
                    Иллюстрации из материалов
                  </Divider>
                  <Space wrap align="start">
                    {result.figures.map((figure) => (
                      <div key={figure.figure_id} style={{ width: 230 }}>
                        <Image
                          src={figuresApi.previewUrl(figure.figure_id)}
                          alt={figure.caption}
                          style={{ background: '#fafafa' }}
                          // У иллюстраций из DOCX координат нет, вырезать нечего
                          fallback="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
                        />
                        <div style={{ fontSize: 12, marginTop: 4 }}>{figure.caption}</div>
                        <div className="stat-hint">
                          {figure.document_title}
                          {figure.page_number ? `, с. ${figure.page_number}` : ''}
                        </div>
                        <div className="stat-hint">
                          {figure.source === 'chunk_page'
                            ? 'со страницы ответа'
                            : 'найдена поиском'}{' '}
                          · {figure.score.toFixed(2)}
                          {figure.labels?.length > 0
                            ? ` · обозначений: ${figure.labels.length}`
                            : ''}
                        </div>
                      </div>
                    ))}
                  </Space>
                </>
              )}
            </Card>
          )}

          {result?.sources?.length > 0 && (
            <Card
              size="small"
              title={`Найденные фрагменты (${result.sources.length})`}
              style={{ marginTop: 16 }}
            >
              <Collapse
                size="small"
                items={result.sources.map((source, index) => ({
                  key: source.chunk_id,
                  label: (
                    <Space>
                      <Tag color="blue">[{index + 1}]</Tag>
                      <span style={{ fontSize: 13 }}>{source.document_title}</span>
                      {source.page_from && (
                        <span className="stat-hint">
                          с. {source.page_from}
                          {source.page_to && source.page_to !== source.page_from
                            ? `–${source.page_to}`
                            : ''}
                        </span>
                      )}
                      <Tag color={source.score > 0.6 ? 'green' : 'orange'}>
                        {source.score.toFixed(3)}
                      </Tag>
                    </Space>
                  ),
                  children: (
                    <div>
                      {source.heading && (
                        <Tag style={{ marginBottom: 8 }}>{source.heading}</Tag>
                      )}
                      <div className="chunk-preview">{source.content}</div>
                    </div>
                  ),
                }))}
              />
            </Card>
          )}

          {result && !result.sources?.length && (
            <Card size="small" style={{ marginTop: 16 }}>
              <Empty description="Подходящих фрагментов в базе не нашлось" />
            </Card>
          )}
        </Col>

        <Col xs={24} lg={8}>
          <Card
            size="small"
            title="Разовые параметры"
            extra={<Switch checked={useOverrides} onChange={setUseOverrides} />}
          >
            <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
              Действуют только на этот запрос, сохранённые настройки не меняются.
              Удобно, чтобы подобрать порог, не трогая работающего бота.
            </Typography.Paragraph>

            <div style={{ opacity: useOverrides ? 1 : 0.45, pointerEvents: useOverrides ? 'auto' : 'none' }}>
              <div style={{ marginBottom: 4, fontSize: 13 }}>Температура</div>
              <Slider
                min={0}
                max={1.5}
                step={0.05}
                value={overrides.temperature}
                onChange={(value) => setOverrides({ ...overrides, temperature: value })}
              />

              <div style={{ marginBottom: 4, fontSize: 13 }}>Порог релевантности</div>
              <Slider
                min={0}
                max={1}
                step={0.01}
                value={overrides.min_relevance_score}
                onChange={(value) =>
                  setOverrides({ ...overrides, min_relevance_score: value })
                }
              />

              <div style={{ marginBottom: 4, fontSize: 13 }}>Фрагментов в контекст</div>
              <InputNumber
                min={1}
                max={20}
                value={overrides.rerank_top_n}
                onChange={(value) => setOverrides({ ...overrides, rerank_top_n: value })}
                style={{ width: '100%' }}
              />
            </div>
          </Card>

          {result && (
            <Card size="small" title="Как отработал запрос" style={{ marginTop: 16 }}>
              <Row gutter={[8, 12]}>
                <Col span={12}>
                  <Statistic
                    title="Поиск"
                    value={result.retrieval_ms}
                    suffix="мс"
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Генерация"
                    value={result.generation_ms}
                    suffix="мс"
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
              </Row>

              <Descriptions
                size="small"
                column={1}
                style={{ marginTop: 12 }}
                items={[
                  {
                    label: 'Всего',
                    children: `${result.total_ms} мс`,
                  },
                  {
                    label: 'Лучшая оценка',
                    children:
                      result.top_score !== null ? result.top_score.toFixed(3) : '—',
                  },
                  { label: 'Модель', children: result.llm_model || '—' },
                  { label: 'Провайдер', children: result.llm_provider || '—' },
                ]}
              />
            </Card>
          )}
        </Col>
      </Row>
    </div>
  )
}
