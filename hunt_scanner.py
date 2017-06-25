import json
import re
import urlparse
from burp import IBurpExtender
from burp import IExtensionStateListener
from burp import IContextMenuFactory
from burp import IContextMenuInvocation
from burp import IScanIssue
from burp import IScannerCheck
from burp import ITab
from java.awt import EventQueue
from java.awt.event import ActionListener
from java.awt.event import ItemListener
from java.awt.event import MouseAdapter
from java.awt.event import MouseEvent
from java.lang import Runnable
from javax.swing import DefaultListModel
from javax.swing import DefaultCellEditor
from javax.swing import JCheckBox
from javax.swing import JComponent
from javax.swing import JEditorPane
from javax.swing import JLabel
from javax.swing import JList
from javax.swing import JMenu
from javax.swing import JMenuBar
from javax.swing import JMenuItem
from javax.swing import JPanel
from javax.swing import JPopupMenu
from javax.swing import JSplitPane
from javax.swing import JScrollPane
from javax.swing import JTable
from javax.swing import JTabbedPane
from javax.swing import JTextArea
from javax.swing import JTree
from javax.swing import ListSelectionModel
from javax.swing import SwingUtilities
from javax.swing.event import ListSelectionListener
from javax.swing.event import PopupMenuListener
from javax.swing.event import TableModelListener
from javax.swing.event import TreeSelectionEvent
from javax.swing.event import TreeSelectionListener
from javax.swing.table import DefaultTableModel
from javax.swing.tree import DefaultMutableTreeNode
from javax.swing.tree import DefaultTreeCellRenderer
from javax.swing.tree import DefaultTreeModel
from javax.swing.tree import TreeSelectionModel
from org.python.core.util import StringUtil

# Using the Runnable class for thread-safety with Swing
class Run(Runnable):
    def __init__(self, runner):
        self.runner = runner

    def run(self):
        self.runner()

class BurpExtender(IBurpExtender, IExtensionStateListener, IContextMenuFactory, IScannerCheck, ITab):
    EXTENSION_NAME = "HUNT - Scanner"

    def __init__(self):
        self.issues = Issues()
        self.view = View(self.issues)

    def registerExtenderCallbacks(self, callbacks):
        self.callbacks = callbacks
        self.view.set_callbacks(callbacks)
        self.helpers = callbacks.getHelpers()
        self.view.set_helpers(self.helpers)
        self.callbacks.registerExtensionStateListener(self)
        self.callbacks.setExtensionName(self.EXTENSION_NAME)
        self.callbacks.addSuiteTab(self)
        self.callbacks.registerContextMenuFactory(self)
        self.callbacks.registerScannerCheck(self)

    def doPassiveScan(self, request_response):
        raw_request = request_response.getRequest()
        raw_response = request_response.getResponse()
        request = self.helpers.analyzeRequest(raw_request)
        response = self.helpers.analyzeResponse(raw_response)

        parameters = request.getParameters()
        url = self.helpers.analyzeRequest(request_response).getUrl()
        vuln_parameters = self.issues.check_parameters(self.helpers, parameters)

        is_not_empty = len(vuln_parameters) > 0

        if is_not_empty:
            self.issues.create_scanner_issues(self.view, self.callbacks, self.helpers, vuln_parameters, request_response)

        # Do not show any Bugcrowd found issues in the Scanner window
        return []

    def createMenuItems(self, invocation):
        return self.view.get_context_menu()

    def getTabCaption(self):
        return self.EXTENSION_NAME

    def getUiComponent(self):
        return self.view.get_pane()

    def extensionUnloaded(self):
        print "HUNT - Scanner plugin unloaded"
        return

class View:
    def __init__(self, issues):
        self.json = issues.get_json()
        self.issues = issues.get_issues()
        self.scanner_issues = issues.get_scanner_issues()
        self.scanner_panes = {}

        self.set_vuln_tree()
        self.set_tree()
        self.set_scanner_panes()
        self.set_pane()
        self.set_tsl()

    def set_callbacks(self, callbacks):
        self.callbacks = callbacks

    def set_helpers(self, helpers):
        self.helpers = helpers

    def get_helpers(self):
        return self.helpers

    def get_issues(self):
        return self.issues

    def get_scanner_issues(self):
        return self.scanner_issues

    def set_vuln_tree(self):
        self.vuln_tree = DefaultMutableTreeNode("Vulnerability Classes")

        vulns = self.json["issues"]

        # TODO: Sort the functionality by name and by vuln class
        for vuln_name in vulns:
            vuln = DefaultMutableTreeNode(vuln_name)
            self.vuln_tree.add(vuln)

            parameters = self.json["issues"][vuln_name]["params"]

            for parameter in parameters:
                param_node = DefaultMutableTreeNode(parameter)
                vuln.add(param_node)

    # Creates a JTree object from the checklist
    def set_tree(self):
        self.tree = JTree(self.vuln_tree)
        self.tree.getSelectionModel().setSelectionMode(
            TreeSelectionModel.SINGLE_TREE_SELECTION
        )

    def get_tree(self):
        return self.tree

    # Creates the tabs dynamically using data from the JSON file
    def set_scanner_panes(self):
        issues = self.issues

        for issue in issues:
            issue_name = issue["name"]
            issue_param = issue["param"]

            key = issue_name + "." + issue_param

            top_pane = self.create_request_list_pane(issue_name)
            bottom_pane = self.create_tabbed_pane()

            scanner_pane = JSplitPane(JSplitPane.VERTICAL_SPLIT, top_pane, bottom_pane)

            self.scanner_panes[key] = scanner_pane

    def get_scanner_panes(self):
        return self.scanner_panes

    def create_request_list_pane(self, issue_name):
        request_list_pane = JScrollPane()

        return request_list_pane

    # Creates a JTabbedPane for each vulnerability per functionality
    def create_tabbed_pane(self):
        tabbed_pane = JTabbedPane()
        tabbed_pane.add("Advisory", JScrollPane())
        tabbed_pane.add("Request", JScrollPane())
        tabbed_pane.add("Response", JScrollPane())

        self.tabbed_pane = tabbed_pane

        return tabbed_pane

    def set_tsl(self):
        tsl = TSL(self)
        self.tree.addTreeSelectionListener(tsl)

        return

    def set_pane(self):
        status = JTextArea()
        status.setLineWrap(True)
        status.setText("Nothing selected")
        self.status = status

        request_list_pane = JScrollPane()

        scanner_pane = JSplitPane(JSplitPane.VERTICAL_SPLIT,
                       request_list_pane,
                       self.tabbed_pane
        )

        self.pane = JSplitPane(JSplitPane.HORIZONTAL_SPLIT,
                    JScrollPane(self.tree),
                    scanner_pane
        )

    def get_pane(self):
        return self.pane

    def create_scanner_pane(self, scanner_pane, issue_name, issue_param):
        scanner_issues = self.get_scanner_issues()
        request_table_pane = scanner_pane.getTopComponent()

        scanner_table_model = ScannerTableModel()
        scanner_table_model.addColumn("Checked")
        scanner_table_model.addColumn("Host")
        scanner_table_model.addColumn("Path")

        for scanner_issue in scanner_issues:
            is_same_name = scanner_issue.getIssueName() == issue_name
            is_same_param = scanner_issue.getParameter() == issue_param
            is_same_issue = is_same_name and is_same_param

            if is_same_issue:
                scanner_table_model.addRow([
                    False,
                    scanner_issue.getHttpService().getHost(),
                    scanner_issue.getUrl()
                ])

        scanner_table = JTable(scanner_table_model)
        scanner_table_listener = IssueListener(self, scanner_table, scanner_pane, issue_name, issue_param)
        scanner_table.getSelectionModel().addListSelectionListener(scanner_table_listener)
        scanner_table.getColumnModel().getColumn(0).setCellEditor(DefaultCellEditor(JCheckBox()))

        request_table_pane.getViewport().setView(scanner_table)
        request_table_pane.revalidate()
        request_table_pane.repaint()

    def set_tabbed_pane(self, scanner_pane, request_list, issue_url, issue_name, issue_param):
        tabbed_pane = scanner_pane.getBottomComponent()
        scanner_issues = self.get_scanner_issues()

        for scanner_issue in scanner_issues:
            is_same_url = scanner_issue.getUrl() == issue_url
            is_same_name = scanner_issue.getIssueName() == issue_name
            is_same_param = scanner_issue.getParameter() == issue_param
            is_same_issue = is_same_url and is_same_name and is_same_param

            if is_same_issue:
                current_issue = scanner_issue
                self.set_context_menu(request_list, scanner_issue)
                break

        print current_issue

        advisory_tab_pane = self.set_advisory_tab_pane(current_issue)
        tabbed_pane.setComponentAt(0, advisory_tab_pane)

        request_tab_pane = self.set_request_tab_pane(current_issue)
        tabbed_pane.setComponentAt(1, request_tab_pane)

        response_tab_pane = self.set_response_tab_pane(current_issue)
        tabbed_pane.setComponentAt(2, response_tab_pane)

    def set_advisory_tab_pane(self, scanner_issue):
        advisory_pane = JEditorPane()
        advisory_pane.setEditable(False)
        advisory_pane.setContentType("text/html")
        advisory_pane.setText("<html>" +
            scanner_issue.getUrl() + "<br><br>" +
            scanner_issue.getIssueDetail() + "</html>"
        )

        # Set a context menu
        self.set_context_menu(advisory_pane, scanner_issue)

        return JScrollPane(advisory_pane)

    def set_request_tab_pane(self, scanner_issue):
        raw_request = scanner_issue.getRequestResponse().getRequest()
        request_body = StringUtil.fromBytes(raw_request)
        request_body = request_body.encode("utf-8")

        request_tab_textarea = JTextArea(request_body)
        request_tab_textarea.setLineWrap(True)

        # Set a context menu
        self.set_context_menu(request_tab_textarea, scanner_issue)

        return JScrollPane(request_tab_textarea)

    def set_response_tab_pane(self, scanner_issue):
        raw_response = scanner_issue.getRequestResponse().getResponse()
        response_body = StringUtil.fromBytes(raw_response)
        response_body = response_body.encode("utf-8")

        response_tab_textarea = JTextArea(response_body)
        response_tab_textarea.setLineWrap(True)

        # Set a context menu
        self.set_context_menu(response_tab_textarea, scanner_issue)

        return JScrollPane(response_tab_textarea)

    # Pass scanner_issue as argument
    def set_context_menu(self, component, scanner_issue):
        context_menu = JPopupMenu()

        repeater = JMenuItem("Send to Repeater")
        repeater.addActionListener(PopupListener(scanner_issue, self.callbacks))

        intruder = JMenuItem("Send to Intruder")
        intruder.addActionListener(PopupListener(scanner_issue, self.callbacks))

        context_menu.add(repeater)
        context_menu.add(intruder)

        context_menu_listener = ContextMenuListener(component, context_menu)
        component.addMouseListener(context_menu_listener)

class ScannerTableModel(DefaultTableModel):
    def __init__(self):
        return

    def getColumnClass(self, col):
        if col == 0:
            return True.__class__
        else:
            return "".__class__

    def isCellEditable(self, row, col):
        return col == 0

class ContextMenuListener(MouseAdapter):
    def __init__(self, component, context_menu):
        self.component = component
        self.context_menu = context_menu

    def mousePressed(self, e):
        is_right_click = SwingUtilities.isRightMouseButton(e)

        if is_right_click:
            self.check(e)

    def check(self, e):
        is_list = type(self.component) == type(JList())

        if is_list:
            is_selection = self.component.getSelectedValue() != None
            is_trigger = e.isPopupTrigger()
            is_context_menu = is_selection and is_trigger
            index = self.component.locationToIndex(e.getPoint())
            self.component.setSelectedIndex(index)

        self.context_menu.show(self.component, e.getX(), e.getY())

class PopupListener(ActionListener):
    def __init__(self, scanner_issue, callbacks):
        self.host = scanner_issue.getHttpService().getHost()
        self.port = scanner_issue.getHttpService().getPort()
        self.protocol = scanner_issue.getHttpService().getProtocol()
        self.request = scanner_issue.getRequestResponse().getRequest()
        self.callbacks = callbacks

        if self.protocol == 443:
            self.use_https = True
        else:
            self.use_https = False

    def actionPerformed(self, e):
        action = str(e.getActionCommand())

        repeater_match = re.search("Repeater", action)
        intruder_match = re.search("Intruder", action)

        is_repeater_match = repeater_match != None
        is_intruder_match = intruder_match != None

        if is_repeater_match:
            print "Sending to Repeater"
            self.callbacks.sendToRepeater(self.host, self.port, self.use_https, self.request, None)

        if is_intruder_match:
            print "Sending to Intruder"
            self.callbacks.sendToIntruder(self.host, self.port, self.use_https, self.request)

class TSL(TreeSelectionListener):
    def __init__(self, view):
        self.view = view
        self.tree = view.get_tree()
        self.pane = view.get_pane()
        self.scanner_issues = view.get_scanner_issues()
        self.scanner_panes = view.get_scanner_panes()

    def valueChanged(self, tse):
        pane = self.pane
        node = self.tree.getLastSelectedPathComponent()

        issue_name = node.getParent().toString()
        issue_param = node.toString()

        issue_name_match = re.search("\(", issue_name)
        issue_param_match = re.search("\(", issue_param)

        is_name_match = issue_name_match != None
        is_param_match = issue_param_match != None

        if is_name_match:
            issue_name = issue_name.split(" (")[0]

        if is_param_match:
            issue_param = issue_param.split(" (")[0]

        is_leaf = node.isLeaf()

        if node:
            if is_leaf:
                key = issue_name + "." + issue_param
                scanner_pane = self.scanner_panes[key]
                self.view.create_scanner_pane(scanner_pane, issue_name, issue_param)
                pane.setRightComponent(scanner_pane)
            else:
                print "No description for " + issue_name + " " + issue_param
        else:
            print "Cannot set a pane for " + issue_name + " " + issue_param

class IssueListener(ListSelectionListener):
    def __init__(self, view, table, scanner_pane, issue_name, issue_param):
        self.view = view
        self.table = table
        self.scanner_pane = scanner_pane
        self.issue_name = issue_name
        self.issue_param = issue_param

    def valueChanged(self, e):
        row = self.table.getSelectedRow()
        url = self.table.getModel().getValueAt(row, 2)
        self.view.set_tabbed_pane(self.scanner_pane, self.table, url, self.issue_name, self.issue_param)

class Issues:
    scanner_issues = []
    total_count = {}

    def __init__(self):
        self.set_json()
        self.set_issues()

    def set_json(self):
        with open("issues.json") as data_file:
            self.json = json.load(data_file)

    def get_json(self):
        return self.json

    def set_issues(self):
        self.issues = []
        issues = self.json["issues"]

        for vuln_name in issues:
            parameters = issues[vuln_name]["params"]

            for parameter in parameters:
                issue = {
                    "name": str(vuln_name),
                    "param": str(parameter),
                    "count": 0
                }

                self.issues.append(issue)

    def get_issues(self):
        return self.issues

    def set_scanner_issues(self, scanner_issue):
        self.scanner_issues.append(scanner_issue)

    def get_scanner_issues(self):
        return self.scanner_issues

    def check_parameters(self, helpers, parameters):
        vuln_params = []
        issues = self.get_issues()

        for parameter in parameters:
            # Make sure that the parameter is not from the cookies
            # https://portswigger.net/burp/extender/api/constant-values.html#burp.IParameter
            is_not_cookie = parameter.getType() != 2

            if is_not_cookie:
                # Handle double URL encoding just in case
                parameter_decoded = helpers.urlDecode(parameter.getName())
                parameter_decoded = helpers.urlDecode(parameter_decoded)
            else:
                continue

            # TODO: Use regex at the beginning and end of the string for params like "id".
            #       Example: id_param, param_id, paramID, etc
            # Check to see if the current parameter is a potentially vuln parameter
            for issue in issues:
                vuln_param = issue["param"]
                is_vuln_found = parameter_decoded == vuln_param

                if is_vuln_found:
                    vuln_params.append(issue)

        return vuln_params

    def create_scanner_issues(self, view, callbacks, helpers, vuln_parameters, request_response):
        # Takes into account if there is more than one vulnerable parameter
        for vuln_parameter in vuln_parameters:
            issues = self.get_issues()
            json = self.get_json()

            issue_name = vuln_parameter["name"]
            issue_param = vuln_parameter["param"]

            url = helpers.analyzeRequest(request_response).getUrl()
            url = urlparse.urlsplit(str(url))
            url = url.scheme + "://" + url.hostname + url.path

            http_service = request_response.getHttpService()
            http_messages = [callbacks.applyMarkers(request_response, None, None)]
            detail = json["issues"][issue_name]["detail"]
            severity = "Medium"

            is_not_dupe = self.check_duplicate_issue(url, issue_param, issue_name)

            if is_not_dupe:
                for issue in issues:
                    is_name = issue["name"] == issue_name
                    is_param = issue["param"] == issue_param
                    is_issue = is_name and is_param

                    if is_issue:
                        issue["count"] += 1
                        issue_count = issue["count"]
                        is_key_exists = issue_name in self.total_count

                        if is_key_exists:
                            self.total_count[issue_name] += 1
                        else:
                            self.total_count[issue_name] = issue_count

                        break

                scanner_issue = ScannerIssue(url, issue_name, issue_param, http_service, http_messages, detail, severity, request_response)
                self.set_scanner_issues(scanner_issue)
                self.add_scanner_count(view, issue_name, issue_param, issue_count, self.total_count[issue_name])

    def check_duplicate_issue(self, url, parameter, issue_name):
        issues = self.get_scanner_issues()

        for issue in issues:
            is_same_url = url == issue.getUrl()
            is_same_parameter = parameter == issue.getParameter()
            is_same_issue_name = issue_name == issue.getIssueName()
            is_dupe = is_same_url and is_same_parameter and is_same_issue_name

            if is_dupe:
                return False

        return True

    def add_scanner_count(self, view, issue_name, issue_param, issue_count, total_count):
        issues = self.get_issues()
        scanner_issues = self.get_scanner_issues()

        tree = view.get_pane().getLeftComponent().getViewport().getView()
        model = tree.getModel()
        root = model.getRoot()
        count = int(root.getChildCount())

        # TODO: Refactor into one function that just takes nodes
        # Iterates through each vulnerability class leaf node in tree
        for i in range(count):
            node = model.getChild(root, i)
            tree_issue_name = node.toString()

            is_issue_name = re.search(issue_name, tree_issue_name)

            if is_issue_name:
                total_issues = 0
                child_count = node.getChildCount()

                # TODO: Refactor into one function that just takes nodes
                # Iterates through each parameter leaf node vulnerability class
                for j in range(child_count):
                    child = node.getChildAt(j)
                    tree_param_name = child.toString()

                    is_param_name = re.search(issue_param, tree_param_name)

                    # Change the display of each parameter leaf node based on
                    # how many issues are found
                    if is_param_name:
                        param_text = issue_param + " (" + str(issue_count) + ")"

                        child.setUserObject(param_text)
                        model.nodeChanged(child)
                        model.reload(node)

                        break

                issue_text = issue_name + " (" + str(total_count) + ")"

                node.setUserObject(issue_text)
                model.nodeChanged(node)
                model.reload(node)

                break

# TODO: Fill out all the getters with proper returns
class ScannerIssue(IScanIssue):
    def __init__(self, url, issue_name, parameter, http_service, http_messages, detail, severity, request_response):
        self.current_url = url
        self.http_service = http_service
        self.http_messages = http_messages
        self.detail = detail.replace("$param$", parameter)
        self.current_severity = severity
        self.request_response = request_response
        self.issue_background = "Bugcrowd"
        self.issue_name = issue_name
        self.parameter = parameter
        self.remediation_background = ""

    def getRequestResponse(self):
        return self.request_response

    def getParameter(self):
        return self.parameter

    def getUrl(self):
        return self.current_url

    def getIssueName(self):
        return self.issue_name

    def getIssueType(self):
        return 0

    def getSeverity(self):
        return self.current_severity

    def getConfidence(self):
        return "Certain"

    def getIssueBackground(self):
        return self.issue_background

    def getRemediationBackground(self):
        return self.remediation_background

    def getIssueDetail(self):
        return self.detail

    def getRemediationDetail(self):
        return None

    def getHttpMessages(self):
        return self.http_messages

    def getHttpService(self):
        return self.http_service

if __name__ in [ '__main__', 'main' ] :
    EventQueue.invokeLater(Run(BurpExtender))
