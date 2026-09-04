import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Progress,
  Rate,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import { DeleteOutlined, PlayCircleOutlined, UploadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import { testing } from '../api/endpoints'

const RUN_STATUS = {
  pending: { color: 'default', label: 'В очереди' },
  running: { color: 'processing', label: 'Выполняется' },
  completed: { color: 'success', label: 'Завершён' },
  failed: { color: 'error', label: 'Ошибка' },
}

export default function Testing() {
  const { message } = App.useApp()
  const [sets, setSets] = useState([])
  const [runs, setRuns] = useState({ items: [], total: 0 })
  const [activeSet, setActiveSet] = useState(null)
  const [questions, setQuestions] = useState([])
  const [results, setResults] = useState(null)
  const [openRun, setOpenRun] = useState(null)
  const [setModal, setSetModal] = useState(false)
  const [questionModal, setQuestionModal] = useState(false)
  const [setForm] = Form.useForm()
  const [questionForm] = Form.useForm()
  const pollRef = useRef(null)

  const loadSets = useCallback(async () => {
    const { data } = await testing.listSets()
    setSets(data)
    if (!activeSet && data.length) setActiveSet(data[0])
  }, [activeSet])

  const loadRuns = useCallback(async () => {
    const { data } = await testing.listRuns({ page: 1, size: 20 })
    setRuns(data)
  }, [])

  const loadQuestions = useCallback(async (setId) => {
    const { data } = await testing.listQuestions(setId)
    setQuestions(data)
  }, [])

  useEffect(() => {
    loadSets()
    loadRuns()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (activeSet) loadQuestions(activeSet.id)
  }, [activeSet, loadQuestions])

  // Прогон идёт в воркере — подтягиваем прогресс, пока он не закончится
  useEffect(() => {
    const hasActive = runs.items.some((run) =>
      ['pending', 'running'].includes(run.status),
    )
    clearInterval(pollRef.current)
    if (hasActive) {
      pollRef.current = setInterval(loadRuns, 3000)
    }
    return () => clearInterval(pollRef.current)
  }, [runs.items, loadRuns])

  const startRun = async (set) => {
    await testing.startRun({ test_set_id: set.id })
    message.success('Прогон запущен')
    loadRuns()
  }

  const openResults = async (run) => {
    setOpenRun(run)
    const { data } = await testing.runResults(run.id)
    setResults(data)
  }

  return (
    <div>
      <div className="page-header">
        <h2>Тестирование</h2>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Как это работает"
        description={
          <span>
            Подготовка эталонных вопросов-ответов. Прогон задаёт их боту
            на текущих настройках и сравнивает ответы с эталоном — оценку ставит модель-судья,
            её можно перекрыть вручную. Отдельно стоит добавить вопросы вне программы с
            галочкой «должен отказаться»: так проверяется, что бот не выдумывает.
          </span>
        }
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card
            title="Наборы вопросов"
            size="small"
            extra={
              <Button size="small" type="primary" onClick={() => setSetModal(true)}>
                Создать
              </Button>
            }
          >
            {sets.length ? (
              <List
                dataSource={sets}
                renderItem={(set) => (
                  <List.Item
                    style={{
                      cursor: 'pointer',
                      background: activeSet?.id === set.id ? '#f0f7ff' : undefined,
                      padding: '10px 12px',
                      borderRadius: 6,
                    }}
                    onClick={() => setActiveSet(set)}
                    actions={[
                      <Button
                        key="run"
                        size="small"
                        type="text"
                        icon={<PlayCircleOutlined />}
                        disabled={!set.questions_count}
                        onClick={(e) => {
                          e.stopPropagation()
                          startRun(set)
                        }}
                      />,
                      <Popconfirm
                        key="delete"
                        title="Удалить набор?"
                        okText="Удалить"
                        cancelText="Отмена"
                        onConfirm={async (e) => {
                          e?.stopPropagation?.()
                          await testing.deleteSet(set.id)
                          setActiveSet(null)
                          loadSets()
                        }}
                      >
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<span style={{ fontSize: 13 }}>{set.name}</span>}
                      description={
                        <span className="stat-hint">
                          {set.questions_count} вопросов
                          {set.section ? ` · ${set.section}` : ''}
                        </span>
                      }
                    />
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="Наборов пока нет" />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          <Card
            title={activeSet ? `Вопросы: ${activeSet.name}` : 'Вопросы'}
            size="small"
            extra={
              activeSet && (
                <Space>
                  <Upload
                    showUploadList={false}
                    beforeUpload={async (file) => {
                      const formData = new FormData()
                      formData.append('file', file)
                      const { data } = await testing.importQuestions(activeSet.id, formData)
                      message.success(data.detail)
                      loadQuestions(activeSet.id)
                      loadSets()
                      return false
                    }}
                  >
                    <Button size="small" icon={<UploadOutlined />}>
                      Импорт CSV
                    </Button>
                  </Upload>
                  <Button size="small" type="primary" onClick={() => setQuestionModal(true)}>
                    Добавить вопрос
                  </Button>
                </Space>
              )
            }
          >
            {activeSet ? (
              <Table
                rowKey="id"
                size="small"
                dataSource={questions}
                pagination={{ pageSize: 10 }}
                columns={[
                  {
                    title: 'Вопрос',
                    dataIndex: 'question',
                    render: (question, row) => (
                      <div>
                        <div style={{ fontSize: 13 }}>{question}</div>
                        {row.should_refuse && (
                          <Tag color="orange" style={{ marginTop: 4 }}>
                            должен отказаться
                          </Tag>
                        )}
                      </div>
                    ),
                  },
                  {
                    title: 'Эталон',
                    dataIndex: 'reference_answer',
                    width: 100,
                    render: (value) =>
                      value ? (
                        <Tag color="green">есть</Tag>
                      ) : (
                        <Tag>нет</Tag>
                      ),
                  },
                  {
                    title: '',
                    width: 50,
                    render: (_, row) => (
                      <Popconfirm
                        title="Удалить вопрос?"
                        okText="Удалить"
                        cancelText="Отмена"
                        onConfirm={async () => {
                          await testing.deleteQuestion(row.id)
                          loadQuestions(activeSet.id)
                          loadSets()
                        }}
                      >
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    ),
                  },
                ]}
              />
            ) : (
              <Empty description="Выберите набор слева" />
            )}
          </Card>
        </Col>
      </Row>

      <Card title="Прогоны" size="small" style={{ marginTop: 16 }}>
        <Table
          rowKey="id"
          size="small"
          dataSource={runs.items}
          pagination={false}
          onRow={(row) => ({
            onClick: () => row.status === 'completed' && openResults(row),
            style: { cursor: row.status === 'completed' ? 'pointer' : 'default' },
          })}
          columns={[
            { title: 'Название', dataIndex: 'name', ellipsis: true },
            {
              title: 'Статус',
              dataIndex: 'status',
              width: 190,
              render: (status, row) => {
                const meta = RUN_STATUS[status]
                if (status === 'running') {
                  return (
                    <div>
                      <Tag color={meta.color}>{meta.label}</Tag>
                      <Progress
                        percent={Math.round(
                          (row.completed_questions / (row.total_questions || 1)) * 100,
                        )}
                        size="small"
                      />
                    </div>
                  )
                }
                return <Tag color={meta.color}>{meta.label}</Tag>
              },
            },
            {
              title: 'Средняя оценка',
              dataIndex: 'avg_score',
              width: 140,
              render: (score) =>
                score === null ? (
                  <span className="stat-hint">—</span>
                ) : (
                  <Tag color={score >= 4 ? 'green' : score >= 3 ? 'orange' : 'red'}>
                    {score.toFixed(2)} / 5
                  </Tag>
                ),
            },
            {
              title: 'Отказы',
              dataIndex: 'refusal_rate',
              width: 100,
              render: (rate) =>
                rate === null ? '—' : `${Math.round(rate * 100)}%`,
            },
            {
              title: 'Задержка',
              dataIndex: 'avg_latency_ms',
              width: 110,
              render: (ms) => (ms ? `${Math.round(ms)} мс` : '—'),
            },
            {
              title: 'Запущен',
              dataIndex: 'created_at',
              width: 140,
              render: (value) => dayjs(value).format('DD.MM.YY HH:mm'),
            },
            {
              title: '',
              width: 50,
              render: (_, row) => (
                <Popconfirm
                  title="Удалить прогон?"
                  okText="Удалить"
                  cancelText="Отмена"
                  onConfirm={async (e) => {
                    e?.stopPropagation?.()
                    await testing.deleteRun(row.id)
                    loadRuns()
                  }}
                >
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => e.stopPropagation()}
                  />
                </Popconfirm>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title="Новый набор вопросов"
        open={setModal}
        onCancel={() => setSetModal(false)}
        onOk={() => setForm.submit()}
        okText="Создать"
        cancelText="Отмена"
      >
        <Form
          form={setForm}
          layout="vertical"
          onFinish={async (values) => {
            await testing.createSet(values)
            message.success('Набор создан')
            setSetModal(false)
            setForm.resetFields()
            loadSets()
          }}
        >
          <Form.Item name="name" label="Название" rules={[{ required: true }]}>
            <Input placeholder="Черепные нервы" />
          </Form.Item>
          <Form.Item name="section" label="Раздел курса">
            <Input placeholder="Неврология" />
          </Form.Item>
          <Form.Item name="description" label="Описание">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Новый контрольный вопрос"
        open={questionModal}
        onCancel={() => setQuestionModal(false)}
        onOk={() => questionForm.submit()}
        okText="Добавить"
        cancelText="Отмена"
        width={620}
      >
        <Form
          form={questionForm}
          layout="vertical"
          onFinish={async (values) => {
            await testing.createQuestion(activeSet.id, values)
            message.success('Вопрос добавлен')
            setQuestionModal(false)
            questionForm.resetFields()
            loadQuestions(activeSet.id)
            loadSets()
          }}
        >
          <Form.Item name="question" label="Вопрос" rules={[{ required: true }]}>
            <Input.TextArea rows={2} placeholder="Какие ветви имеет наружная сонная артерия?" />
          </Form.Item>
          <Form.Item
            name="reference_answer"
            label="Эталонный ответ"
            extra="С ним модель-судья сравнивает ответ бота"
          >
            <Input.TextArea rows={6} />
          </Form.Item>
          <Form.Item name="expected_source" label="Ожидаемый источник">
            <Input placeholder="Сапин, том 2, с. 45" />
          </Form.Item>
          <Form.Item
            name="should_refuse"
            label="Бот должен отказаться"
            valuePropName="checked"
            extra="Для вопросов вне программы — проверка, что бот не выдумывает"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={`Результаты: ${openRun?.name || ''}`}
        open={!!openRun}
        onClose={() => {
          setOpenRun(null)
          setResults(null)
        }}
        width={860}
      >
        {openRun && (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Statistic
                  title="Средняя оценка"
                  value={openRun.avg_score?.toFixed(2) ?? '—'}
                  suffix="/ 5"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="Доля отказов"
                  value={Math.round((openRun.refusal_rate || 0) * 100)}
                  suffix="%"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="Средняя задержка"
                  value={Math.round(openRun.avg_latency_ms || 0)}
                  suffix="мс"
                />
              </Col>
            </Row>

            <List
              dataSource={results || []}
              renderItem={(item) => (
                <List.Item style={{ display: 'block' }}>
                  <Card size="small" style={{ width: '100%' }}>
                    <Typography.Text strong style={{ fontSize: 13 }}>
                      {item.question}
                    </Typography.Text>

                    <Descriptions
                      size="small"
                      column={3}
                      style={{ marginTop: 8 }}
                      items={[
                        {
                          label: 'Судья',
                          children:
                            item.judge_score !== null ? (
                              <Tag
                                color={
                                  item.judge_score >= 4
                                    ? 'green'
                                    : item.judge_score >= 3
                                      ? 'orange'
                                      : 'red'
                                }
                              >
                                {item.judge_score}
                              </Tag>
                            ) : (
                              '—'
                            ),
                        },
                        {
                          label: 'Отказ',
                          children: item.refused ? 'да' : 'нет',
                        },
                        {
                          label: 'Релевантн.',
                          children: item.top_score?.toFixed(2) ?? '—',
                        },
                      ]}
                    />

                    {item.judge_comment && (
                      <Typography.Paragraph
                        type="secondary"
                        style={{ fontSize: 12, marginTop: 4 }}
                      >
                        {item.judge_comment}
                      </Typography.Paragraph>
                    )}

                    <div className="chunk-preview" style={{ marginTop: 8 }}>
                      {item.answer || '(нет ответа)'}
                    </div>

                    <Space style={{ marginTop: 10 }} align="center">
                      <span style={{ fontSize: 12 }}>Оценка преподавателя:</span>
                      <Rate
                        count={5}
                        value={item.manual_score || 0}
                        onChange={async (value) => {
                          await testing.setManualScore(item.id, { manual_score: value })
                          message.success('Оценка сохранена')
                          const { data } = await testing.runResults(openRun.id)
                          setResults(data)
                        }}
                      />
                    </Space>
                  </Card>
                </List.Item>
              )}
            />
          </>
        )}
      </Drawer>
    </div>
  )
}
