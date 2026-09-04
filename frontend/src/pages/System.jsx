import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

import { auth, health } from '../api/endpoints'
import { useAuthStore } from '../store/auth'

function ComponentCard({ title, state, extra }) {
  const ok = state?.ok
  return (
    <Card size="small" title={title}>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        <Badge
          status={ok ? 'success' : 'error'}
          text={ok ? 'работает' : 'недоступен'}
        />
        {state?.error && (
          <div className="stat-hint" style={{ color: '#d4380d' }}>
            {state.error}
          </div>
        )}
        {extra}
      </Space>
    </Card>
  )
}

export default function System() {
  const { message } = App.useApp()
  const currentUser = useAuthStore((state) => state.user)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [users, setUsers] = useState([])
  const [userModal, setUserModal] = useState(false)
  const [passwordModal, setPasswordModal] = useState(false)
  const [userForm] = Form.useForm()
  const [passwordForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await health.full()
      setStatus(data)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadUsers = useCallback(async () => {
    if (!currentUser?.is_superuser) return
    try {
      const { data } = await auth.listUsers()
      setUsers(data)
    } catch {
      // не суперпользователь — раздел просто не показываем
    }
  }, [currentUser])

  useEffect(() => {
    load()
    loadUsers()
  }, [load, loadUsers])

  return (
    <div>
      <div
        className="page-header"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}
      >
        <div>
          <h2>Система</h2>
          <div className="subtitle">Состояние компонентов и учётные записи</div>
        </div>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>
          Обновить
        </Button>
      </div>

      {status?.status === 'degraded' && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="Часть компонентов недоступна"
          description="Бот может отвечать с ошибками. Проверьте карточки ниже и логи контейнеров."
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <ComponentCard title="База данных" state={status?.database} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <ComponentCard title="Redis" state={status?.redis} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <ComponentCard
            title="Эмбеддинги"
            state={status?.embeddings}
            extra={
              status?.embeddings && (
                <div className="stat-hint">
                  {status.embeddings.embedding_model}
                  <br />
                  устройство: {status.embeddings.device}
                </div>
              )
            }
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <ComponentCard
            title="Языковая модель"
            state={status?.llm}
            extra={
              status?.llm && (
                <div className="stat-hint">
                  {status.llm.model}
                  <br />
                  провайдер: {status.llm.provider}
                </div>
              )
            }
          />
        </Col>
      </Row>

      <Card title="ВКонтакте" size="small" style={{ marginTop: 16 }}>
        <Descriptions
          size="small"
          column={2}
          items={[
            {
              label: 'Бот включён',
              children: status?.vk?.enabled ? (
                <Tag color="green">да</Tag>
              ) : (
                <Tag>нет</Tag>
              ),
            },
            {
              label: 'Токен сообщества',
              children: status?.vk?.configured ? (
                <Tag color="green">задан</Tag>
              ) : (
                <Tag color="orange">не задан</Tag>
              ),
            },
          ]}
        />
        <div className="stat-hint" style={{ marginTop: 8 }}>
          Настраивается переменными VK_ENABLED, VK_GROUP_TOKEN и VK_GROUP_ID в файле .env
          на сервере — после изменения нужно перезапустить контейнер vkbot.
        </div>
      </Card>

      <Card
        title="Учётные записи"
        size="small"
        style={{ marginTop: 16 }}
        extra={
          <Space>
            <Button size="small" onClick={() => setPasswordModal(true)}>
              Сменить свой пароль
            </Button>
            {currentUser?.is_superuser && (
              <Button size="small" type="primary" onClick={() => setUserModal(true)}>
                Добавить
              </Button>
            )}
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          dataSource={users}
          pagination={false}
          locale={{ emptyText: 'Список доступен суперпользователю' }}
          columns={[
            { title: 'E-mail', dataIndex: 'email' },
            {
              title: 'Имя',
              dataIndex: 'full_name',
              render: (value) => value || <span className="stat-hint">—</span>,
            },
            {
              title: 'Права',
              dataIndex: 'is_superuser',
              width: 170,
              render: (value) =>
                value ? <Tag color="blue">суперпользователь</Tag> : <Tag>администратор</Tag>,
            },
            {
              title: 'Последний вход',
              dataIndex: 'last_login_at',
              width: 160,
              render: (value) =>
                value ? dayjs(value).format('DD.MM.YYYY HH:mm') : '—',
            },
            {
              title: '',
              width: 50,
              render: (_, row) =>
                currentUser?.is_superuser && row.id !== currentUser.id ? (
                  <Popconfirm
                    title="Удалить учётную запись?"
                    okText="Удалить"
                    cancelText="Отмена"
                    onConfirm={async () => {
                      await auth.deleteUser(row.id)
                      message.success('Учётная запись удалена')
                      loadUsers()
                    }}
                  >
                    <Button size="small" type="text" danger>
                      Удалить
                    </Button>
                  </Popconfirm>
                ) : null,
            },
          ]}
        />
      </Card>

      <Modal
        title="Новая учётная запись"
        open={userModal}
        onCancel={() => setUserModal(false)}
        onOk={() => userForm.submit()}
        okText="Создать"
        cancelText="Отмена"
      >
        <Form
          form={userForm}
          layout="vertical"
          onFinish={async (values) => {
            await auth.createUser(values)
            message.success('Учётная запись создана')
            setUserModal(false)
            userForm.resetFields()
            loadUsers()
          }}
        >
          <Form.Item
            name="email"
            label="E-mail"
            rules={[{ required: true, type: 'email', message: 'Укажите корректный e-mail' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label="Пароль"
            rules={[{ required: true, min: 8, message: 'Минимум 8 символов' }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="full_name" label="Имя">
            <Input />
          </Form.Item>
          <Form.Item name="is_superuser" label="Суперпользователь" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Смена пароля"
        open={passwordModal}
        onCancel={() => setPasswordModal(false)}
        onOk={() => passwordForm.submit()}
        okText="Сменить"
        cancelText="Отмена"
      >
        <Form
          form={passwordForm}
          layout="vertical"
          onFinish={async (values) => {
            await auth.changePassword(values.current_password, values.new_password)
            message.success('Пароль изменён')
            setPasswordModal(false)
            passwordForm.resetFields()
          }}
        >
          <Form.Item
            name="current_password"
            label="Текущий пароль"
            rules={[{ required: true }]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="Новый пароль"
            rules={[{ required: true, min: 8, message: 'Минимум 8 символов' }]}
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
