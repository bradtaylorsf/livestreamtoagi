export const moveAction = {
    name: '!move',
    aliases: ['!walk', '!step'],
    description:
        'Move a verified number of blocks ' +
        'and report the outcome.',
    params: {
        action_id: {
            type: 'string',
            description: 'Caller-provided action id echoed in action.result.',
        },
        direction: {
            type: 'string',
            optional: false,
            description: 'forward, back, left, right, up, down, north, south, east, or west.',
        },
        distance_blocks: {
            type: 'float',
            description: 'Requested movement distance in blocks.',
        },
        timeout_ms: {
            type: 'int',
            optional: true,
            description: 'Optional movement deadline in milliseconds.',
        },
    },
    perform: async function (agent, action_id, direction, distance_blocks, timeout_ms) {
        return `${agent.name}:${action_id}:${direction}:${distance_blocks}:${timeout_ms}`;
    },
};

export default moveAction;
