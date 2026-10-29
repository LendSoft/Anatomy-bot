import { useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Avatar, Dropdown, Layout, Menu } from 'antd'
import {
  ApiOutlined,
  BookOutlined,
  ContactsOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LogoutOutlined,
  MessageOutlined,
  PictureOutlined,
  SettingOutlined,
  TranslationOutlined,
  UserOutlined,
} from '@ant-design/icons'

import { useAuthStore } from '../store/auth'

const { Header, Sider, Content } = Layout

const MENU_ITEMS = [
  { key: '/', icon: <DashboardOutlined />, label: <Link to="/">Дашборд</Link> },
  {
    key: '/documents',
    icon: <BookOutlined />,
    label: <Link to="/documents">Материалы</Link>,
  },
  {
    key: '/figures',
    icon: <PictureOutlined />,
    label: <Link to="/figures">Иллюстрации</Link>,
  },
  {
    key: '/glossary',
    icon: <TranslationOutlined />,
    label: <Link to="/glossary">Термины</Link>,
  },
  {
    key: '/organization',
    icon: <ContactsOutlined />,
    label: <Link to="/organization">Орг. информация</Link>,
  },
  {
    key: '/prompts',
    icon: <FileTextOutlined />,
    label: <Link to="/prompts">Промпты</Link>,
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: <Link to="/settings">Параметры</Link>,
  },
  {
    key: '/playground',
    icon: <MessageOutlined />,
    label: <Link to="/playground">Проверка</Link>,
  },
  {
    key: '/testing',
    icon: <ExperimentOutlined />,
    label: <Link to="/testing">Тестирование</Link>,
  },
  { key: '/logs', icon: <FileTextOutlined />, label: <Link to="/logs">Логи</Link> },
  { key: '/system', icon: <ApiOutlined />, label: <Link to="/system">Система</Link> },
]

export default function AdminLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        width={218}
      >
        <div
          style={{
            padding: collapsed ? '14px 8px' : '18px 20px',
            borderBottom: '1px solid #f0f0f0',
            marginBottom: 8,
            textAlign: 'center',
          }}
        >
          {/* В свёрнутом виде помещается только эмблема, в развёрнутом —
              логотип с названием университета */}
          <img
            src={collapsed ? '/samgmu-logo.png' : '/samgmu-panel.png'}
            alt="СамГМУ"
            style={{
              maxWidth: '100%',
              height: collapsed ? 34 : 46,
              objectFit: 'contain',
              display: 'block',
              margin: '0 auto',
            }}
          />
          {!collapsed && (
            <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 6 }}>
              панель управления
            </div>
          )}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={MENU_ITEMS}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Dropdown
            menu={{
              items: [
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: 'Выйти',
                  onClick: handleLogout,
                },
              ],
            }}
          >
            <div style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{user?.email}</span>
            </div>
          </Dropdown>
        </Header>

        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
