export const missingDescription = {
    name: '!missingDescription',
    params: {
        reason: {
            type: 'string',
        },
    },
    perform: async function (_agent, reason) {
        return reason;
    },
};
