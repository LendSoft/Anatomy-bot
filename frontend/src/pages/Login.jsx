import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined, MailOutlined } from '@ant-design/icons'

import { useAuthStore } from '../store/auth'

export default function Login() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const navigate = useNavigate()
  const { login, user } = useAuthStore()

  useEffect(() => {
    if (user) navigate('/', { replace: true })
  }, [user, navigate])

  const onFinish = async (values) => {
    setLoading(true)
    setError(null)
    try {
      await login(values.email, values.password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail || 'Не удалось войти')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background: '#f5f6f8',
        padding: 16,
      }}
    >
      <Card style={{ width: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <img
            src="/samgmu-panel.png"
            alt="СамГМУ"
            style={{ height: 56, objectFit: 'contain', marginBottom: 12 }}
          />
          <Typography.Title level={5} style={{ marginBottom: 4, fontWeight: 500 }}>
            Панель управления
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            Образовательный бот по анатомии человека
          </Typography.Text>
        </div>

        {error && (
          <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} />
        )}

        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item
            name="email"
            label="E-mail"
            rules={[{ required: true, message: 'Укажите e-mail' }]}
          >
            <Input prefix={<MailOutlined />} placeholder="admin@example.ru" size="large" />
          </Form.Item>

          <Form.Item
            name="password"
            label="Пароль"
            rules={[{ required: true, message: 'Укажите пароль' }]}
          >
            <Input.Password prefix={<LockOutlined />} size="large" />
          </Form.Item>

          <Button type="primary" htmlType="submit" loading={loading} block size="large">
            Войти
          </Button>
        </Form>
      </Card>
    </div>
  )
}
