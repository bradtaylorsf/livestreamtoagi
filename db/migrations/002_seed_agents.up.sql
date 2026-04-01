-- 002_seed_agents.up.sql
-- Seeds the agents table with the 9 project agents.
-- Uses ON CONFLICT DO NOTHING for idempotency.

INSERT INTO agents (id, display_name, model_conversation, model_building, voice_id, status)
VALUES
    ('vera',     'Vera',         'claude-haiku-4-5',  'claude-sonnet-4-6',     'en-GB-SoniaNeural',        'active'),
    ('rex',      'Rex',          'claude-haiku-4-5',  'claude-sonnet-4-6',     'en-US-GuyNeural',          'active'),
    ('aurora',   'Aurora',       'gemini-flash',      'gemini-2.5-pro',        'en-US-JennyNeural',        'active'),
    ('pixel',    'Pixel',        'gpt-4o-mini',       'gpt-5.2',              'en-US-DavisNeural',        'active'),
    ('fork',     'Fork',         'deepseek-v3.2',     'deepseek-v3.2',        'en-AU-WilliamNeural',      'active'),
    ('sentinel', 'Sentinel',     'claude-haiku-4-5',  'claude-haiku-4-5',     'en-US-AriaNeural',         'active'),
    ('grok',     'Grok',         'grok-3-mini',       'grok-3',               'en-US-ChristopherNeural',  'active'),
    ('overseer', 'The Overseer', 'claude-haiku-4-5',  'claude-haiku-4-5',     'en-US-AndrewNeural',       'active'),
    ('alpha',    'Alpha',        'deepseek-v3.2',     'deepseek-v3.2',        NULL,                       'active')
ON CONFLICT (id) DO NOTHING;
